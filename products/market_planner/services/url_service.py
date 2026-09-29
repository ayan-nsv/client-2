"""SSRF-safe HTTPS URL validation and bounded downloads."""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests

# Private, loopback, link-local, and IPv6 ULA (fc00::/7)
_IPV6_ULA = ipaddress.IPv6Network("fc00::/7")

_DEFAULT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB
_DEFAULT_TIMEOUT = 30
_CHUNK_SIZE = 8192
_MAX_REDIRECTS = 3
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class SafeUrlFetchError(ValueError):
    """Client-provided URL failed SSRF or policy checks."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip in _IPV6_ULA:
        return True
    return False


def _resolve_host_ips(hostname: str, port: int) -> Iterable[str]:
    try:
        infos = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise SafeUrlFetchError(f"Could not resolve host: {hostname}") from exc

    if not infos:
        raise SafeUrlFetchError(f"Could not resolve host: {hostname}")

    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        yield ip_str


def assert_public_https_url(url: str) -> None:
    """
    Require https:// and ensure the hostname does not resolve to
    private, loopback, link-local, or IPv6 ULA addresses.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() != "https":
        raise SafeUrlFetchError("Only https:// image URLs are allowed")
    if not parsed.hostname:
        raise SafeUrlFetchError("Invalid image URL: missing hostname")
    if parsed.username or parsed.password:
        raise SafeUrlFetchError("Image URLs must not include credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    port = parsed.port or 443

    try:
        literal = ipaddress.ip_address(hostname)
        if _is_blocked_ip(literal):
            raise SafeUrlFetchError("Image URL host is not allowed")
        return
    except ValueError:
        pass

    for ip_str in _resolve_host_ips(hostname, port):
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise SafeUrlFetchError("Image URL host is not allowed") from exc
        if _is_blocked_ip(ip):
            raise SafeUrlFetchError("Image URL host is not allowed")


def download_https_bytes(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    headers: dict[str, str] | None = None,
 ) -> bytes:
    """
    Download bytes from a user-supplied HTTPS URL with SSRF checks,
    redirect re-validation, and a response size cap.
    """
    assert_public_https_url(url)

    current = url.strip()
    request_headers = headers or {"User-Agent": "Marketing-App/1.0"}

    for redirect_count in range(_MAX_REDIRECTS + 1):
        assert_public_https_url(current)

        try:
            response = requests.get(
                current,
                stream=True,
                timeout=timeout,
                headers=request_headers,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise SafeUrlFetchError(f"Failed to download image: {exc}") from exc

        if response.status_code in _REDIRECT_STATUS_CODES:
            if redirect_count >= _MAX_REDIRECTS:
                raise SafeUrlFetchError("Too many redirects while downloading image")
            location = response.headers.get("Location")
            if not location:
                raise SafeUrlFetchError("Redirect response missing Location header")
            current = urljoin(current, location)
            response.close()
            continue

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise SafeUrlFetchError(f"Failed to download image: HTTP {response.status_code}") from exc

        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    raise SafeUrlFetchError(
                        f"Image exceeds maximum size of {max_bytes} bytes"
                    )
            except ValueError as exc:
                raise SafeUrlFetchError("Invalid Content-Length header") from exc

        content = bytearray()
        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > max_bytes:
                raise SafeUrlFetchError(
                    f"Image exceeds maximum size of {max_bytes} bytes"
                )

        return bytes(content)

    raise SafeUrlFetchError("Too many redirects while downloading image")
