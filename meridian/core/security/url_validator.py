"""URL validation with SSRF protections for remote video / user URLs."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

# Default allow-list of public video hosts (extend via config as needed).
DEFAULT_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "m.youtube.com",
)


class URLValidationError(ValueError):
    """Raised when a URL fails scheme / host / SSRF checks."""


@dataclass(frozen=True, slots=True)
class URLValidationConfig:
    """Tunables for remote URL validation and download limits."""

    allowed_schemes: tuple[str, ...] = ("https",)
    allowed_host_suffixes: tuple[str, ...] = DEFAULT_ALLOWED_HOST_SUFFIXES
    allow_any_public_https: bool = False
    # Explicit IP allow-list for otherwise-blocked ranges (empty by default).
    ip_allowlist: tuple[str, ...] = ()
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    max_download_bytes: int = 512 * 1024 * 1024  # 512 MiB
    resolve_dns: bool = True


@dataclass(frozen=True, slots=True)
class ValidatedURL:
    """A URL that passed scheme, host, and SSRF checks."""

    url: str
    hostname: str
    resolved_ips: tuple[str, ...] = ()
    config: URLValidationConfig = field(default_factory=URLValidationConfig)


def _hostname_allowed(hostname: str, suffixes: tuple[str, ...]) -> bool:
    host = hostname.lower().rstrip(".")
    for suffix in suffixes:
        s = suffix.lower().rstrip(".")
        if host == s or host.endswith("." + s):
            return True
    return False


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for loopback, private, link-local, metadata, etc."""
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_host(hostname: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise URLValidationError(f"DNS resolution failed for host {hostname!r}: {exc}") from exc
    ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        addr = str(sockaddr[0])
        if addr not in ips:
            ips.append(addr)
    if not ips:
        raise URLValidationError(f"No addresses resolved for host {hostname!r}")
    return tuple(ips)


def validate_remote_url(
    url: str,
    config: URLValidationConfig | None = None,
    *,
    resolver: Callable[[str], tuple[str, ...]] | None = None,
) -> ValidatedURL:
    """Validate a user-supplied remote URL for safe fetching.

    Enforces HTTPS, optional host allow-list, and SSRF protections by resolving
    DNS and rejecting private / link-local / loopback / metadata addresses
    unless explicitly allow-listed.
    """
    cfg = config or URLValidationConfig()
    if not url or not url.strip():
        raise URLValidationError("URL must be a non-empty string")

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in cfg.allowed_schemes:
        raise URLValidationError(
            f"URL scheme {scheme!r} not allowed; permitted: {cfg.allowed_schemes}"
        )
    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise URLValidationError("URLs with embedded credentials are not allowed")

    # Literal IP in hostname — check immediately.
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if str(literal_ip) not in cfg.ip_allowlist and _is_blocked_ip(literal_ip):
            raise URLValidationError(f"Blocked IP address in URL host: {hostname}")
        return ValidatedURL(
            url=url.strip(),
            hostname=hostname,
            resolved_ips=(str(literal_ip),),
            config=cfg,
        )

    if not cfg.allow_any_public_https and not _hostname_allowed(
        hostname, cfg.allowed_host_suffixes
    ):
        raise URLValidationError(
            f"Host {hostname!r} is not in the allow-list {cfg.allowed_host_suffixes}"
        )

    resolve = resolver or _resolve_host
    resolved: tuple[str, ...] = ()
    if cfg.resolve_dns:
        resolved = tuple(resolve(hostname))
        for ip_str in resolved:
            if ip_str in cfg.ip_allowlist:
                continue
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise URLValidationError(f"Invalid resolved address {ip_str!r}") from exc
            if _is_blocked_ip(ip):
                raise URLValidationError(
                    f"Host {hostname!r} resolves to blocked address {ip_str} (SSRF protection)"
                )

    return ValidatedURL(
        url=url.strip(),
        hostname=hostname,
        resolved_ips=resolved,
        config=cfg,
    )


async def download_validated_url(
    validated: ValidatedURL,
    *,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Download a previously validated URL with size and timeout caps."""
    cfg = validated.config
    timeout = httpx.Timeout(
        connect=cfg.connect_timeout_seconds,
        read=cfg.read_timeout_seconds,
        write=cfg.read_timeout_seconds,
        pool=cfg.connect_timeout_seconds,
    )
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        async with http.stream("GET", validated.url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > cfg.max_download_bytes:
                    raise URLValidationError(
                        f"Download exceeded max size of {cfg.max_download_bytes} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
    finally:
        if owns_client:
            await http.aclose()
