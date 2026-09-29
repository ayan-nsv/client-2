"""Shared network and Selenium helpers for scraper runs."""
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse


_BLOCKED_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}


class UnsafeUrlError(ValueError):
    """Raised when a URL targets a local/internal network resource."""
    pass


def get_required_chromedriver_path() -> str:
    """
    Return the pinned/local ChromeDriver path.

    Runtime downloads are intentionally forbidden; Docker sets CHROMEDRIVER_PATH
    to the baked-in chromium-driver binary.
    """
    driver_path = (
        os.environ.get("CHROMEDRIVER_PATH")
        or os.environ.get("CHROME_DRIVER_PATH")
        or ""
    ).strip()
    if not driver_path:
        raise RuntimeError("CHROMEDRIVER_PATH must be set to a local ChromeDriver binary")
    if not os.path.exists(driver_path):
        raise RuntimeError(f"CHROMEDRIVER_PATH does not exist: {driver_path}")
    return driver_path


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in _BLOCKED_METADATA_IPS
    )


def validate_public_http_url(url: str) -> str:
    """Allow only public http(s) URLs and reject local/internal DNS targets."""
    clean_url = str(url).strip()
    parsed = urlparse(clean_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrlError("Only public http(s) URLs are allowed")

    host = parsed.hostname
    try:
        if _is_blocked_ip(host):
            raise UnsafeUrlError("URL resolves to a blocked IP range")
        return clean_url
    except ValueError:
        pass

    try:
        resolved = {
            result[4][0]
            for result in socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise UnsafeUrlError("URL host could not be resolved") from exc

    if not resolved or any(_is_blocked_ip(ip) for ip in resolved):
        raise UnsafeUrlError("URL resolves to a blocked IP range")
    return clean_url


validate_public_url = validate_public_http_url


def _safe_request(requests_like, method: str, url: str, **kwargs):
    """Validate URL and every redirect before making a requests-compatible call."""
    current_url = validate_public_http_url(url)
    allow_redirects = kwargs.pop("allow_redirects", method.lower() in ("get", "options"))
    max_redirects = int(kwargs.pop("max_redirects", 5))

    for _ in range(max_redirects + 1):
        response = requests_like.request(
            method,
            current_url,
            allow_redirects=False,
            **kwargs,
        )
        if not allow_redirects or not response.is_redirect:
            return response

        location = response.headers.get("location")
        if not location:
            return response
        current_url = validate_public_http_url(urljoin(current_url, location))

    raise UnsafeUrlError("Too many redirects while validating URL")


def safe_get(requests_like, url: str, **kwargs):
    """Validate URL before performing a requests-compatible GET."""
    return _safe_request(requests_like, "GET", url, **kwargs)


def safe_head(requests_like, url: str, **kwargs):
    """Validate URL before performing a requests-compatible HEAD."""
    return _safe_request(requests_like, "HEAD", url, **kwargs)


def safe_post(requests_like, url: str, **kwargs):
    """Validate URL before performing a requests-compatible POST."""
    return _safe_request(requests_like, "POST", url, **kwargs)


def safe_put(requests_like, url: str, **kwargs):
    """Validate URL before performing a requests-compatible PUT."""
    return _safe_request(requests_like, "PUT", url, **kwargs)


def safe_driver_get(driver, url: str) -> None:
    """Validate URL before allowing Selenium to navigate."""
    driver.get(validate_public_http_url(url))


def _seccomp_is_enforced() -> bool:
    """Return True when Linux seccomp filtering is active for this process."""
    try:
        with open("/proc/self/status", encoding="utf-8") as status_file:
            for line in status_file:
                if line.startswith("Seccomp:"):
                    return line.split(":", 1)[1].strip() == "2"
    except OSError:
        return False
    return False


def add_chrome_no_sandbox_if_needed(options) -> None:
    """
    Add --no-sandbox only for the hardened container case: non-root POSIX user
    with seccomp filtering active. This avoids disabling Chrome's sandbox on
    root or unconfined hosts.
    """
    override = os.environ.get("CHROME_NO_SANDBOX", "").strip().lower()
    if override in ("0", "false", "no"):
        return
    if os.name != "posix":
        return
    try:
        if os.getuid() != 0 and _seccomp_is_enforced():
            options.add_argument("--no-sandbox")
    except AttributeError:
        pass
