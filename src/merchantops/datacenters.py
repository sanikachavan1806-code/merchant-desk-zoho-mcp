from __future__ import annotations

from urllib.parse import urlparse

from merchantops.errors import ConfigError

# Zoho runs eight regional account + API hosts. Indian Razorpay merchants
# almost always belong on `in`.
DATACENTERS: dict[str, tuple[str, str]] = {
    "us": ("https://accounts.zoho.com", "https://www.zohoapis.com"),
    "eu": ("https://accounts.zoho.eu", "https://www.zohoapis.eu"),
    "in": ("https://accounts.zoho.in", "https://www.zohoapis.in"),
    "au": ("https://accounts.zoho.com.au", "https://www.zohoapis.com.au"),
    "jp": ("https://accounts.zoho.jp", "https://www.zohoapis.jp"),
    "ca": ("https://accounts.zohocloud.ca", "https://www.zohoapis.ca"),
    "sa": ("https://accounts.zoho.sa", "https://www.zohoapis.sa"),
    "cn": ("https://accounts.zoho.com.cn", "https://www.zohoapis.com.cn"),
}

ALLOWED_API_HOSTS = {urlparse(api).hostname for _, api in DATACENTERS.values()}


def resolve_datacenter(dc: str) -> tuple[str, str]:
    key = (dc or "").strip().lower()
    if key not in DATACENTERS:
        known = ", ".join(sorted(DATACENTERS))
        raise ConfigError(f"Unknown Zoho datacenter '{dc}'. Use one of: {known}.")
    return DATACENTERS[key]


def validate_api_domain(url: str) -> str:
    """Accept a token ``api_domain`` only if it is a known Zoho API host."""

    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_API_HOSTS:
        raise ConfigError(f"Refusing unexpected Zoho api_domain '{url}'.")
    return f"https://{parsed.hostname}"
