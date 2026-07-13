"""Secret loading with environment-aware backends.

Production never reads API keys from process environment variables — those
paths use Google Secret Manager (service-account auth). Local development
loads from a gitignored ``.env`` file via python-dotenv.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any


class AppEnvironment(StrEnum):
    """Deployment environment controlling how secrets are sourced."""

    LOCAL = "local"
    PRODUCTION = "production"
    TEST = "test"


_PLACEHOLDER_RE = re.compile(
    r"(?i)^(changeme|change.?me|your[-_]?api[-_]?key|todo|replace.?me|xxx+|dummy|"
    r"example|placeholder|not[-_]?a[-_]?real[-_]?key|sk-xxx+|INSERT.*HERE|<.*|)$"
)

# Names that must never be pulled from os.environ in production code paths.
_PRODUCTION_FORBIDDEN_ENV_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "MERIDIAN_OPENAI_API_KEY",
        "MERIDIAN_ANTHROPIC_API_KEY",
    }
)


class SecretError(RuntimeError):
    """Raised when a secret is missing, placeholder, or unlawfully sourced."""


class SecretStore(ABC):
    """Abstract secret backend."""

    @abstractmethod
    def get(self, name: str) -> str | None:
        """Return secret value or None if absent."""


class DotEnvSecretStore(SecretStore):
    """Local-dev store backed by a ``.env`` file (never used in production)."""

    def __init__(
        self, env_file: str | Path | None = None, values: Mapping[str, str] | None = None
    ) -> None:
        self._values: dict[str, str] = dict(values or {})
        if values is None:
            path = Path(env_file or ".env")
            if path.is_file():
                from dotenv import dotenv_values

                loaded = dotenv_values(path)
                self._values = {k: v for k, v in loaded.items() if k and v is not None}

    def get(self, name: str) -> str | None:
        return self._values.get(name)


class GoogleSecretManagerStore(SecretStore):
    """Production store using Google Secret Manager.

    Secrets are addressed as logical names (e.g. ``openai-api-key``) and
    resolved to ``projects/{project}/secrets/{name}/versions/latest``.
    """

    def __init__(
        self,
        project_id: str,
        *,
        client: Any | None = None,
        version: str = "latest",
    ) -> None:
        if not project_id:
            raise SecretError("Google Secret Manager requires a GCP project id")
        self._project_id = project_id
        self._version = version
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import secretmanager

            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    def get(self, name: str) -> str | None:
        client = self._get_client()
        resource = f"projects/{self._project_id}/secrets/{name}/versions/{self._version}"
        try:
            response = client.access_secret_version(request={"name": resource})
        except Exception as exc:  # normalized at boundary
            raise SecretError(f"Failed to access secret {name!r} from GSM: {exc}") from exc
        payload = response.payload.data.decode("utf-8")
        return str(payload)


def detect_environment(raw: str | None = None) -> AppEnvironment:
    """Map ``MERIDIAN_ENV`` / ``APP_ENV`` to a known environment."""
    value = (raw or os.getenv("MERIDIAN_ENV") or os.getenv("APP_ENV") or "local").strip().lower()
    if value in {"prod", "production"}:
        return AppEnvironment.PRODUCTION
    if value in {"test", "testing", "ci"}:
        return AppEnvironment.TEST
    return AppEnvironment.LOCAL


def looks_like_placeholder(value: str) -> bool:
    """Return True if the secret is empty or an obvious placeholder."""
    stripped = value.strip()
    if not stripped:
        return True
    if _PLACEHOLDER_RE.match(stripped):
        return True
    # Common dummy patterns embedded in longer strings
    lowered = stripped.lower()
    markers = ("changeme", "your-api-key", "replace-me", "not-a-real", "example-key")
    return any(marker in lowered for marker in markers)


def require_secret(name: str, value: str | None) -> str:
    """Validate a secret value or raise ``SecretError`` (boot-fatal)."""
    if value is None:
        raise SecretError(f"Required secret {name!r} is missing")
    if looks_like_placeholder(value):
        raise SecretError(
            f"Required secret {name!r} looks like a placeholder or empty value; refusing to boot"
        )
    return value


@dataclass(frozen=True, slots=True)
class RuntimeSecrets:
    """Validated secrets available after boot checks."""

    environment: AppEnvironment
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gcp_project: str | None = None


def build_secret_store(
    environment: AppEnvironment,
    *,
    project_id: str | None = None,
    env_file: str | Path | None = None,
    gsm_client: Any | None = None,
    local_values: Mapping[str, str] | None = None,
) -> SecretStore:
    """Construct the appropriate store for the environment.

    Production always uses Google Secret Manager and never reads API keys
    from ``os.environ``. Local/test use ``.env`` / injected maps.
    """
    if environment is AppEnvironment.PRODUCTION:
        # Guardrail: refuse if someone tries to rely on process env API keys.
        for key in _PRODUCTION_FORBIDDEN_ENV_KEYS:
            if os.environ.get(key):
                raise SecretError(
                    f"Production boot refuses API key {key} from environment variables; "
                    "use Google Secret Manager instead"
                )
        project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        if not project:
            raise SecretError(
                "Production requires GOOGLE_CLOUD_PROJECT (or GCP_PROJECT) for Secret Manager"
            )
        return GoogleSecretManagerStore(project, client=gsm_client)
    return DotEnvSecretStore(env_file=env_file, values=local_values)


def load_runtime_secrets(
    *,
    environment: AppEnvironment | None = None,
    store: SecretStore | None = None,
    require_openai: bool = False,
    require_anthropic: bool = False,
    require_gcp_project: bool = False,
) -> RuntimeSecrets:
    """Load and optionally validate secrets for process boot."""
    env = environment or detect_environment()
    secret_store = store or build_secret_store(env)

    def _get(*names: str) -> str | None:
        for name in names:
            value = secret_store.get(name)
            if value is not None and value.strip():
                return value
        return None

    openai = _get("openai-api-key", "OPENAI_API_KEY", "MERIDIAN_OPENAI_API_KEY")
    anthropic = _get("anthropic-api-key", "ANTHROPIC_API_KEY", "MERIDIAN_ANTHROPIC_API_KEY")
    gcp_project = _get("gcp-project", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT")

    if require_openai:
        openai = require_secret("openai-api-key", openai)
    elif openai is not None and looks_like_placeholder(openai):
        raise SecretError("openai-api-key looks like a placeholder; refusing to boot")

    if require_anthropic:
        anthropic = require_secret("anthropic-api-key", anthropic)
    elif anthropic is not None and looks_like_placeholder(anthropic):
        raise SecretError("anthropic-api-key looks like a placeholder; refusing to boot")

    if require_gcp_project or env is AppEnvironment.PRODUCTION:
        gcp_project = require_secret("gcp-project", gcp_project)

    return RuntimeSecrets(
        environment=env,
        openai_api_key=openai,
        anthropic_api_key=anthropic,
        gcp_project=gcp_project,
    )


def assert_boot_secrets(secrets: RuntimeSecrets) -> None:
    """Final startup gate — raises ``SecretError`` if boot must abort."""
    if secrets.environment is AppEnvironment.PRODUCTION and not secrets.gcp_project:
        raise SecretError("Production boot requires a validated gcp-project secret")
    # Re-check any present keys for placeholders (defense in depth).
    for name, value in (
        ("openai-api-key", secrets.openai_api_key),
        ("anthropic-api-key", secrets.anthropic_api_key),
    ):
        if value is not None and looks_like_placeholder(value):
            raise SecretError(f"Boot refused: {name} is a placeholder")


@lru_cache(maxsize=1)
def get_cached_runtime_secrets() -> RuntimeSecrets:
    """Process-wide secrets loaded once at first access."""
    return load_runtime_secrets()
