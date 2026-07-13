"""SSRF / remote URL validation tests."""

from __future__ import annotations

import pytest

from meridian.core.security.url_validator import (
    URLValidationConfig,
    URLValidationError,
    download_validated_url,
    validate_remote_url,
)


def test_https_youtube_allowed_with_public_ip() -> None:
    validated = validate_remote_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        resolver=lambda _host: ("142.250.72.14",),
    )
    assert validated.hostname == "www.youtube.com"


def test_http_rejected() -> None:
    with pytest.raises(URLValidationError, match="scheme"):
        validate_remote_url("http://www.youtube.com/watch?v=x", resolver=lambda _h: ("1.1.1.1",))


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/video.mp4",
        "https://10.0.0.5/clip",
        "https://192.168.1.10/x",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/video",
    ],
)
def test_literal_private_ips_blocked(url: str) -> None:
    with pytest.raises(URLValidationError, match=r"Blocked IP|blocked"):
        validate_remote_url(url, config=URLValidationConfig(allow_any_public_https=True))


def test_dns_to_private_ip_blocked() -> None:
    with pytest.raises(URLValidationError, match="SSRF"):
        validate_remote_url(
            "https://www.youtube.com/watch?v=x",
            resolver=lambda _h: ("10.1.2.3",),
        )


def test_dns_to_metadata_ip_blocked() -> None:
    with pytest.raises(URLValidationError, match=r"SSRF|blocked"):
        validate_remote_url(
            "https://www.youtube.com/watch?v=x",
            resolver=lambda _h: ("169.254.169.254",),
        )


def test_unknown_host_rejected_by_allowlist() -> None:
    with pytest.raises(URLValidationError, match="allow-list"):
        validate_remote_url(
            "https://evil.example/video.mp4",
            resolver=lambda _h: ("1.2.3.4",),
        )


def test_embedded_credentials_rejected() -> None:
    with pytest.raises(URLValidationError, match="credentials"):
        validate_remote_url(
            "https://user:pass@www.youtube.com/watch?v=x",
            resolver=lambda _h: ("1.2.3.4",),
        )


@pytest.mark.asyncio
async def test_download_enforces_max_size() -> None:
    class _Stream:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"a" * 100
            yield b"b" * 100

        async def __aenter__(self) -> _Stream:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class _Client:
        def stream(self, *_a: object, **_k: object) -> _Stream:
            return _Stream()

        async def aclose(self) -> None:
            return None

    validated = validate_remote_url(
        "https://www.youtube.com/watch?v=x",
        config=URLValidationConfig(max_download_bytes=150, resolve_dns=False),
        resolver=lambda _h: ("1.1.1.1",),
    )
    # resolve_dns False still needs host allow-list; re-validate with public fake IP path
    validated = validate_remote_url(
        "https://www.youtube.com/watch?v=x",
        config=URLValidationConfig(max_download_bytes=150),
        resolver=lambda _h: ("1.1.1.1",),
    )
    with pytest.raises(URLValidationError, match="max size"):
        await download_validated_url(validated, client=_Client())  # type: ignore[arg-type]
