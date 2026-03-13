from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# API key prefix for identification
API_KEY_PREFIX = "bsg_"
API_KEY_BYTES = 32


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (plaintext_key, key_prefix).
        The plaintext key is shown to the user once.
        The key_prefix (first 8 chars after ``bsg_``) is stored for identification.
    """
    raw = secrets.token_urlsafe(API_KEY_BYTES)
    key = f"{API_KEY_PREFIX}{raw}"
    prefix = key[: len(API_KEY_PREFIX) + 8]
    return key, prefix


def hash_api_key(key: str) -> str:
    """Hash an API key for storage using SHA-256.

    We use SHA-256 rather than bcrypt because API keys are high-entropy
    random tokens (not user-chosen passwords) and we need fast lookups.
    """
    return hashlib.sha256(key.encode()).hexdigest()


def verify_api_key(key: str, key_hash: str) -> bool:
    """Verify an API key against its stored hash."""
    return hmac.compare_digest(hash_api_key(key), key_hash)


# ---------------------------------------------------------------------------
# AES-256-GCM encryption for provider API keys
# ---------------------------------------------------------------------------

_AES_NONCE_BYTES = 12
_AES_TAG_BYTES = 16


def _get_cipher(encryption_key: bytes):
    """Lazy import cryptography and return an AESGCM instance."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(encryption_key)


def encrypt_value(plaintext: str, encryption_key: bytes) -> str:
    """Encrypt a string value using AES-256-GCM.

    Returns a base64-encoded string: ``nonce || ciphertext || tag``.
    """
    cipher = _get_cipher(encryption_key)
    nonce = os.urandom(_AES_NONCE_BYTES)
    ciphertext = cipher.encrypt(nonce, plaintext.encode(), None)
    return b64encode(nonce + ciphertext).decode()


def decrypt_value(encrypted: str, encryption_key: bytes) -> str:
    """Decrypt an AES-256-GCM encrypted string."""
    cipher = _get_cipher(encryption_key)
    raw = b64decode(encrypted)
    nonce = raw[:_AES_NONCE_BYTES]
    ciphertext = raw[_AES_NONCE_BYTES:]
    return cipher.decrypt(nonce, ciphertext, None).decode()


# ---------------------------------------------------------------------------
# JWT tokens (lightweight, no external dependency beyond PyJWT)
# ---------------------------------------------------------------------------

_JWT_ALGORITHM = "HS256"
_JWT_DEFAULT_EXPIRY = timedelta(hours=24)


@dataclass
class TokenPayload:
    """Decoded JWT token payload."""

    tenant_id: str
    scopes: list[str]
    exp: datetime


def create_jwt(
    tenant_id: str,
    jwt_secret: str,
    scopes: list[str] | None = None,
    expires_delta: timedelta = _JWT_DEFAULT_EXPIRY,
) -> str:
    """Create a JWT token for a tenant."""
    import jwt

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": tenant_id,
        "scopes": scopes or [],
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str, jwt_secret: str) -> TokenPayload:
    """Decode and validate a JWT token.

    Raises ``jwt.InvalidTokenError`` on any validation failure.
    """
    import jwt

    payload = jwt.decode(token, jwt_secret, algorithms=[_JWT_ALGORITHM])
    return TokenPayload(
        tenant_id=payload["sub"],
        scopes=payload.get("scopes", []),
        exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
