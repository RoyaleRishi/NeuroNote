"""Unit tests for API key encryption helpers."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import decrypt_api_key, encrypt_api_key, InvalidToken


def test_encrypt_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
    plaintext = "sk-test-key-abc123"
    assert decrypt_api_key(encrypt_api_key(plaintext)) == plaintext


def test_no_key_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PREF_ENCRYPTION_KEY is unset, functions return the value unchanged."""
    monkeypatch.delenv("PREF_ENCRYPTION_KEY", raising=False)
    value = "sk-test-key-abc123"
    assert encrypt_api_key(value) == value
    assert decrypt_api_key(value) == value


def test_tampered_ciphertext_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        decrypt_api_key("not-a-valid-fernet-token")


def test_empty_string_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREF_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert decrypt_api_key(encrypt_api_key("")) == ""
