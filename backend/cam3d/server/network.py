"""Local network helpers (LAN addresses for the pairing QR code)."""
from __future__ import annotations

import ipaddress
import socket


def lan_addresses() -> list[str]:
    """Private IPv4 addresses of this machine, best guess first. Sends no packet."""
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # UDP connect: route lookup only
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out: list[str] = []
    for ip in found:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_private and not a.is_loopback and ip not in out:
            out.append(ip)
    return out
