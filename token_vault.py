"""Authenticated encryption for provider refresh tokens.

Keys are supplied only through server-side environment configuration. The
database stores ciphertext and a key version; no token or key is logged.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
from typing import Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TokenVaultError(RuntimeError):
    pass


def generate_encryption_key() -> str:
    """Generate a URL-safe 256-bit key; print/store it only in a secret manager."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _decode_key(value: str) -> bytes:
    try:
        padded = value.strip() + ("=" * (-len(value.strip()) % 4))
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:
        raise TokenVaultError("Token encryption key is not valid URL-safe base64") from exc
    if len(key) != 32:
        raise TokenVaultError("Token encryption keys must decode to exactly 32 bytes")
    return key


def _keyring(env: Mapping[str, str]) -> tuple[str, dict[str, bytes]]:
    raw = env.get("NEXUS_TOKEN_ENCRYPTION_KEYS_JSON", "").strip()
    current = env.get("NEXUS_TOKEN_ENCRYPTION_KEY_VERSION", "v1").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", current):
        raise TokenVaultError("Token encryption key version is invalid")
    if raw:
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TokenVaultError("Token encryption keyring JSON is invalid") from exc
        if not isinstance(values, dict) or not values:
            raise TokenVaultError("Token encryption keyring must be a non-empty object")
        keys = {}
        for version, encoded in values.items():
            if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", version):
                raise TokenVaultError("Token encryption keyring contains an invalid version")
            if not isinstance(encoded, str):
                raise TokenVaultError("Token encryption keyring values must be strings")
            keys[version] = _decode_key(encoded)
    else:
        encoded = env.get("NEXUS_TOKEN_ENCRYPTION_KEY", "").strip()
        if not encoded:
            raise TokenVaultError("NEXUS_TOKEN_ENCRYPTION_KEY or keyring is required")
        keys = {current: _decode_key(encoded)}
    if current not in keys:
        raise TokenVaultError("Current token encryption key version is missing from the keyring")
    return current, keys


def encrypt_refresh_token(token: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if env is None else env
    if not isinstance(token, str) or not token.strip():
        raise TokenVaultError("Refresh token must be a non-empty string")
    version, keys = _keyring(values)
    nonce = secrets.token_bytes(12)
    aad = f"nexus:youtube:refresh:{version}".encode("utf-8")
    ciphertext = AESGCM(keys[version]).encrypt(nonce, token.encode("utf-8"), aad)
    return {"ciphertext_hex": (nonce + ciphertext).hex(), "key_version": version}


def decrypt_refresh_token(
    ciphertext_hex: str,
    key_version: str,
    env: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if env is None else env
    _, keys = _keyring(values)
    key = keys.get(key_version)
    if key is None:
        raise TokenVaultError("Token encryption key version is unavailable")
    try:
        raw = bytes.fromhex(ciphertext_hex)
        if len(raw) < 12 + 16:
            raise ValueError("ciphertext too short")
        nonce, ciphertext = raw[:12], raw[12:]
        aad = f"nexus:youtube:refresh:{key_version}".encode("utf-8")
        return AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
    except Exception as exc:
        raise TokenVaultError("Encrypted refresh token could not be authenticated") from exc
