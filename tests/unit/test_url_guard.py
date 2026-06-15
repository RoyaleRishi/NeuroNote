"""Unit tests for url_guard.validate_outbound_url — SSRF prevention.

Tests are offline-safe: hostname resolution is monkeypatched so tests do not
make real DNS calls and remain deterministic in CI.
"""
from __future__ import annotations

import socket

import pytest

from app.core.url_guard import validate_outbound_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_getaddrinfo(ip: str):
    """Return a monkeypatch target that pretends *host* resolves to *ip*."""
    addr = (socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))

    def _fake(host, port, *args, **kwargs):  # noqa: ANN001
        return [addr]

    return _fake


# ---------------------------------------------------------------------------
# Scheme / structure rejections (no DNS needed — caught before resolution)
# ---------------------------------------------------------------------------


def test_rejects_http_scheme() -> None:
    """Non-HTTPS URLs must be rejected regardless of host."""
    with pytest.raises(ValueError, match="https"):
        validate_outbound_url("http://api.openai.com/v1")


def test_rejects_empty_string() -> None:
    with pytest.raises(ValueError):
        validate_outbound_url("")


def test_rejects_no_scheme() -> None:
    with pytest.raises(ValueError):
        validate_outbound_url("api.openai.com/v1")


def test_rejects_ftp_scheme() -> None:
    with pytest.raises(ValueError, match="https"):
        validate_outbound_url("ftp://api.openai.com/v1")


# ---------------------------------------------------------------------------
# Private / reserved IP literals — caught before DNS lookup
# ---------------------------------------------------------------------------


def test_rejects_loopback_ipv4_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    """127.0.0.1 is loopback — always rejected."""
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("127.0.0.1"))
    with pytest.raises(ValueError, match="private|loopback|reserved|non-public"):
        validate_outbound_url("https://127.0.0.1")


def test_rejects_private_10_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """10.x.x.x is RFC-1918 private."""
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("10.0.0.1"))
    with pytest.raises(ValueError, match="private|loopback|reserved|non-public"):
        validate_outbound_url("https://10.0.0.1")


def test_rejects_private_192_168_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """192.168.x.x is RFC-1918 private."""
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("192.168.1.1"))
    with pytest.raises(ValueError, match="private|loopback|reserved|non-public"):
        validate_outbound_url("https://192.168.1.1")


def test_rejects_link_local_metadata_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """169.254.169.254 is the AWS/GCP/Azure instance metadata endpoint."""
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("169.254.169.254"))
    with pytest.raises(ValueError, match="private|loopback|reserved|non-public"):
        validate_outbound_url("https://169.254.169.254")


# ---------------------------------------------------------------------------
# Hostname resolution failures — fail closed
# ---------------------------------------------------------------------------


def test_rejects_non_resolving_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hosts that fail DNS resolution must be rejected (fail-closed)."""

    def _raise(host, port, *args, **kwargs):  # noqa: ANN001
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(ValueError, match="resolve|DNS|lookup"):
        validate_outbound_url("https://this-host-does-not-exist.invalid")


# ---------------------------------------------------------------------------
# Allowed public URLs
# ---------------------------------------------------------------------------


def test_allows_openai_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """api.openai.com must pass validation."""
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("104.18.7.192"))
    validate_outbound_url("https://api.openai.com/v1")  # must not raise


def test_allows_anthropic_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """api.anthropic.com must pass validation."""
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("160.79.104.16"))
    validate_outbound_url("https://api.anthropic.com/v1")  # must not raise


def test_allows_custom_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any custom HTTPS host resolving to a globally-routable public IP must pass.

    We use 8.8.8.8 (Google Public DNS) as a well-known public address —
    it is not in any RFC-1918/link-local/reserved/documentation range.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _mock_getaddrinfo("8.8.8.8"))
    validate_outbound_url("https://my-llm-proxy.example.com/v1")  # must not raise
