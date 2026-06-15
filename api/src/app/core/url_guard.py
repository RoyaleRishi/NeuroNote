"""SSRF prevention: validate outbound URLs before sending user-supplied values to LLM calls.

Policy:
- Scheme must be ``https`` (reject ``http``, ``ftp``, etc.).
- Host must resolve via DNS (fail closed on resolution error).
- Every resolved address must be a public, routable IP — loopback, private,
  link-local, reserved, multicast, and unspecified ranges are all rejected.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse

__all__ = ["validate_outbound_url"]


def validate_outbound_url(url: str) -> None:
    """Raise ``ValueError`` if *url* is not safe to use as an outbound LLM endpoint.

    Checks performed (in order):
    1. Scheme must be ``https``.
    2. A hostname must be present.
    3. The hostname resolves via DNS (fail closed).
    4. Every resolved IP must be a globally-routable public address.

    Raises:
        ValueError: with a human-readable message explaining why the URL was rejected.
    """
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != "https":
        raise ValueError(
            f"LLM base URL must use the https scheme (got '{parsed.scheme or '(none)'}')."
        )

    host = parsed.hostname
    if not host:
        raise ValueError("LLM base URL must include a hostname.")

    # Resolve the host to one or more addresses; fail closed on DNS error.
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(
            f"LLM base URL host '{host}' could not be resolved via DNS: {exc}"
        ) from exc

    if not addr_infos:
        raise ValueError(f"LLM base URL host '{host}' returned no DNS records.")

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        # sockaddr is (ip, port) for AF_INET and (ip, port, flow, scope) for AF_INET6.
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            # Malformed address — treat as unsafe.
            raise ValueError(
                f"LLM base URL host '{host}' resolved to an unparseable address: {ip_str!r}."
            )

        if (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise ValueError(
                f"LLM base URL host '{host}' resolves to a non-public address "
                f"({ip_str}) which is not allowed."
            )
