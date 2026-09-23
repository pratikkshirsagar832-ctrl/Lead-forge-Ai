"""Encryption at rest for third-party OAuth tokens (LinkedIn).

Fernet (AES-128-CBC + HMAC-SHA256) keyed by ``LINKEDIN_TOKEN_KEY``. Tokens
are encrypted before they touch the database and are never returned to the
browser. Generate a key with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class TokenCryptoError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _fernet(key: str) -> Fernet:
    if not key:
        raise TokenCryptoError("LINKEDIN_TOKEN_KEY is not configured")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise TokenCryptoError("LINKEDIN_TOKEN_KEY is not a valid Fernet key") from exc


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None or plaintext == "":
        return None
    return _fernet(get_settings().linkedin_token_key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet(get_settings().linkedin_token_key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenCryptoError("stored token could not be decrypted (wrong LINKEDIN_TOKEN_KEY?)") from exc
