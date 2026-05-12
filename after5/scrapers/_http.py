from __future__ import annotations
"""Shared HTTP helper — polite UA, short timeout, no retries, SSRF-locked.

We refuse to hit private/loopback/link-local IPs OR cloud metadata endpoints,
because scraper inputs ultimately come from uploaded CSVs. Without this
filter a hostile CSV with `domain=169.254.169.254` would let the scraper
fetch the cloud-provider metadata endpoint and leak instance credentials.
"""
import ipaddress
import socket
from urllib.parse import urlparse

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"}

BLOCK_HOSTS = {
    # Cloud metadata
    "169.254.169.254",         # AWS / GCP / Azure IMDS
    "metadata.google.internal",
    "metadata",
    # Localhost / sentinel
    "localhost", "127.0.0.1", "0.0.0.0",
}


def _host_resolves_safely(host: str) -> bool:
    """True only if `host` resolves to a public IP and isn't in BLOCK_HOSTS."""
    if not host:
        return False
    h = host.lower().strip(".")
    if h in BLOCK_HOSTS:
        return False
    # Resolve and ensure every returned IP is public.
    try:
        infos = socket.getaddrinfo(h, None)
    except OSError:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return False
    return True


def _safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname:
        return False
    return _host_resolves_safely(parsed.hostname)


def get(url: str, timeout: int = 10) -> requests.Response | None:
    """Polite GET with SSRF guard. Returns None on any failure."""
    if not _safe_url(url):
        return None
    try:
        # allow_redirects=False so a redirect to 169.254.169.254 can't bypass
        # our pre-flight host check. We follow up to 3 hops manually.
        current = url
        for _ in range(4):
            r = requests.get(current, headers=HEADERS, timeout=timeout,
                             allow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                if not loc or not _safe_url(loc):
                    return None
                current = loc
                continue
            return r
        return None
    except requests.RequestException:
        return None
