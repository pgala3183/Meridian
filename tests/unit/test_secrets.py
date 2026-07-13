"""Unit tests for secret loading and boot checks."""

from __future__ import annotations

import pytest

from meridian.secrets import (
    AppEnvironment,
    DotEnvSecretStore,
    GoogleSecretManagerStore,
    SecretError,
    assert_boot_secrets,
    build_secret_store,
    detect_environment,
    load_runtime_secrets,
    looks_like_placeholder,
    require_secret,
)
from meridian.secrets.loader import RuntimeSecrets


def test_detect_environment() -> None:
    assert detect_environment("production") is AppEnvironment.PRODUCTION
    assert detect_environment("prod") is AppEnvironment.PRODUCTION
    assert detect_environment("test") is AppEnvironment.TEST
    assert detect_environment("local") is AppEnvironment.LOCAL


def test_placeholder_detection() -> None:
    assert looks_like_placeholder("")
    assert looks_like_placeholder("changeme")
    assert looks_like_placeholder("your-api-key")
    assert looks_like_placeholder("sk-your-api-key-here")
    assert not looks_like_placeholder("sk-live-real-looking-key-9f3a")


def test_require_secret_rejects_placeholder() -> None:
    with pytest.raises(SecretError, match="placeholder"):
        require_secret("openai-api-key", "changeme")
    with pytest.raises(SecretError, match="missing"):
        require_secret("openai-api-key", None)


def test_local_store_from_mapping() -> None:
    store = DotEnvSecretStore(values={"OPENAI_API_KEY": "sk-live-real-looking-key-9f3a"})
    secrets = load_runtime_secrets(
        environment=AppEnvironment.LOCAL,
        store=store,
        require_openai=True,
    )
    assert secrets.openai_api_key is not None
    assert_boot_secrets(secrets)


def test_production_refuses_env_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-real-looking-key-9f3a")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-proj")
    with pytest.raises(SecretError, match="environment variables"):
        build_secret_store(AppEnvironment.PRODUCTION)


def test_production_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with pytest.raises(SecretError, match="GOOGLE_CLOUD_PROJECT"):
        build_secret_store(AppEnvironment.PRODUCTION)


def test_gsm_store_reads_via_injected_client() -> None:
    class _Payload:
        data = b"sk-live-real-looking-key-9f3a"

    class _Response:
        payload = _Payload()

    class _Client:
        def access_secret_version(self, request: dict[str, str]) -> _Response:
            assert "openai-api-key" in request["name"]
            return _Response()

    store = GoogleSecretManagerStore("demo-proj", client=_Client())
    assert store.get("openai-api-key") == "sk-live-real-looking-key-9f3a"


def test_boot_refuses_missing_prod_project() -> None:
    secrets = RuntimeSecrets(environment=AppEnvironment.PRODUCTION, gcp_project=None)
    with pytest.raises(SecretError, match="gcp-project"):
        assert_boot_secrets(secrets)
