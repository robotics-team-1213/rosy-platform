"""Screen-code and manual-address input checks (D-361), split from enrollment.py (D-766 4)."""

from __future__ import annotations

import ipaddress

from fleet.server.enrollment_errors import EnrollmentError

CODE_ALPHABET = frozenset("23456789ABCDEFGHJKMNPQRSTUVWXYZ")
CODE_LENGTH = 8
DEFAULT_PORT = 8080
#: The console applies the same RFC 1918 rule before sending (web/enrollment.js).
_RFC1918 = tuple(ipaddress.ip_network(net) for net in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def normalize_code(text: object) -> str:
    """Drop spaces and hyphens, uppercase, check the alphabet before any robot call."""
    if not isinstance(text, str):
        raise EnrollmentError("bad_format", 400, "a screen code is 8 characters like ABCD-EFGH")
    code = "".join(ch for ch in text if ch not in " -\t").upper()
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        raise EnrollmentError("bad_format", 400, "a screen code is 8 characters like ABCD-EFGH")
    return code


def parse_manual_address(text: object) -> str:
    """Private LAN IPv4[:port] only; `.local`, hostnames and public addresses are refused."""
    if not isinstance(text, str) or not text.strip():
        raise EnrollmentError("bad_address", 400, "enter the robot's private LAN IPv4 address, optionally with :port")
    host, _, port_text = text.strip().partition(":")
    try:
        ip = ipaddress.ip_address(host)
        port = int(port_text) if port_text else DEFAULT_PORT
    except ValueError:
        raise EnrollmentError("bad_address", 400,
                              "enter the robot's private LAN IPv4 address, optionally with :port") from None
    if (ip.version != 4 or not any(ip in net for net in _RFC1918)
            or not 1 <= port <= 65535):
        raise EnrollmentError("bad_address", 400, "only private LAN IPv4 addresses are accepted")
    return f"{ip}:{port}"
