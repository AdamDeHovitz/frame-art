"""Validate the explicit private-network address used for LAN sharing."""

import ipaddress
from urllib.parse import urlsplit


def normalize_origin(value):
    try:
        parsed = urlsplit(value)
        address = ipaddress.IPv4Address(parsed.hostname)
        networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
        if (parsed.scheme != "http" or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment
                or not any(address in ipaddress.IPv4Network(n) for n in networks)):
            raise ValueError
        port = parsed.port if parsed.port is not None else 80
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Use a private IPv4 address, such as 192.168.1.20.") from None
    return f"http://{address}" + (f":{port}" if port != 80 else "")
