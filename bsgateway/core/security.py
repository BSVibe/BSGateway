from __future__ import annotations

import os
from base64 import b64decode, b64encode

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
