"""Fernet-based encryption for sensitive preference values (llm_api_key).

PREF_ENCRYPTION_KEY must be a base64url-encoded 32-byte Fernet key.
Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

When the env var is unset, both functions are no-ops (plaintext stored/returned).
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["encrypt_api_key", "decrypt_api_key", "InvalidToken"]


def _get_fernet() -> Fernet | None:
    raw = os.getenv("PREF_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    return Fernet(raw.encode())


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt plaintext; no-op if PREF_ENCRYPTION_KEY is unset."""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt ciphertext; no-op if PREF_ENCRYPTION_KEY is unset.

    Raises ``InvalidToken`` if the key is set but ciphertext is invalid/tampered.
    """
    f = _get_fernet()
    if f is None:
        return ciphertext
    return f.decrypt(ciphertext.encode()).decode()
