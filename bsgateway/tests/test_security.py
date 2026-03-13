"""Tests for bsgateway.core.security module."""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

from bsgateway.core.security import (
    API_KEY_PREFIX,
    create_jwt,
    decode_jwt,
    decrypt_value,
    encrypt_value,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)


class TestApiKeyGeneration:
    def test_generate_api_key_format(self):
        key, prefix = generate_api_key()
        assert key.startswith(API_KEY_PREFIX)
        assert prefix == key[: len(API_KEY_PREFIX) + 8]
        assert len(key) > 20

    def test_generate_api_key_uniqueness(self):
        keys = {generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10

    def test_hash_and_verify(self):
        key, _ = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed)
        assert not verify_api_key("wrong_key", hashed)

    def test_hash_is_deterministic(self):
        key = "bsg_test_key_12345"
        assert hash_api_key(key) == hash_api_key(key)

    def test_hash_is_different_for_different_keys(self):
        h1 = hash_api_key("bsg_key1")
        h2 = hash_api_key("bsg_key2")
        assert h1 != h2


class TestEncryption:
    @pytest.fixture
    def encryption_key(self) -> bytes:
        return os.urandom(32)

    def test_encrypt_decrypt_roundtrip(self, encryption_key: bytes):
        plaintext = "sk-ant-api03-secret-key-here"
        encrypted = encrypt_value(plaintext, encryption_key)
        decrypted = decrypt_value(encrypted, encryption_key)
        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_different_encryptions_produce_different_output(self, encryption_key: bytes):
        plaintext = "same-value"
        e1 = encrypt_value(plaintext, encryption_key)
        e2 = encrypt_value(plaintext, encryption_key)
        # Different nonces should produce different ciphertext
        assert e1 != e2
        # But both decrypt to the same value
        assert decrypt_value(e1, encryption_key) == plaintext
        assert decrypt_value(e2, encryption_key) == plaintext

    def test_wrong_key_fails_to_decrypt(self, encryption_key: bytes):
        encrypted = encrypt_value("secret", encryption_key)
        wrong_key = os.urandom(32)
        with pytest.raises(Exception):
            decrypt_value(encrypted, wrong_key)

    def test_empty_string_encryption(self, encryption_key: bytes):
        encrypted = encrypt_value("", encryption_key)
        assert decrypt_value(encrypted, encryption_key) == ""

    def test_unicode_encryption(self, encryption_key: bytes):
        plaintext = "한국어 API 키: sk-test-123"
        encrypted = encrypt_value(plaintext, encryption_key)
        assert decrypt_value(encrypted, encryption_key) == plaintext


class TestJWT:
    JWT_SECRET = "test-secret-key-for-jwt-signing"

    def test_create_and_decode(self):
        token = create_jwt("tenant-123", self.JWT_SECRET, scopes=["admin"])
        payload = decode_jwt(token, self.JWT_SECRET)
        assert payload.tenant_id == "tenant-123"
        assert payload.scopes == ["admin"]

    def test_default_scopes_empty(self):
        token = create_jwt("tenant-456", self.JWT_SECRET)
        payload = decode_jwt(token, self.JWT_SECRET)
        assert payload.scopes == []

    def test_wrong_secret_fails(self):
        import jwt

        token = create_jwt("tenant-789", self.JWT_SECRET)
        with pytest.raises(jwt.InvalidSignatureError):
            decode_jwt(token, "wrong-secret")

    def test_expired_token_fails(self):
        import jwt

        token = create_jwt(
            "tenant-expired",
            self.JWT_SECRET,
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_jwt(token, self.JWT_SECRET)

    def test_expiry_is_set(self):
        token = create_jwt(
            "tenant-exp",
            self.JWT_SECRET,
            expires_delta=timedelta(hours=2),
        )
        payload = decode_jwt(token, self.JWT_SECRET)
        assert payload.exp is not None
