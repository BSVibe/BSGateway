"""Tests for bsgateway.core.security module."""

from __future__ import annotations

import os

import pytest

from bsgateway.core.security import (
    decrypt_value,
    encrypt_value,
)


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
