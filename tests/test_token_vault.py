import base64
import json
import unittest

from token_vault import (
    TokenVaultError,
    decrypt_refresh_token,
    encrypt_refresh_token,
    generate_encryption_key,
    validate_token_vault_config,
)


class TokenVaultTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip_never_stores_plaintext(self):
        key = generate_encryption_key()
        env = {
            "NEXUS_TOKEN_ENCRYPTION_KEY": key,
            "NEXUS_TOKEN_ENCRYPTION_KEY_VERSION": "v1",
        }
        token = "refresh-token-value-never-store-plaintext"
        encrypted = encrypt_refresh_token(token, env)
        self.assertEqual(encrypted["key_version"], "v1")
        self.assertNotIn(token, encrypted["ciphertext_hex"])
        self.assertEqual(decrypt_refresh_token(encrypted["ciphertext_hex"], "v1", env), token)

    def test_ciphertext_tampering_and_unknown_key_version_fail_closed(self):
        env = {"NEXUS_TOKEN_ENCRYPTION_KEY": generate_encryption_key()}
        encrypted = encrypt_refresh_token("secret-refresh-token", env)
        tampered = encrypted["ciphertext_hex"][:-2] + ("00" if encrypted["ciphertext_hex"][-2:] != "00" else "ff")
        with self.assertRaises(TokenVaultError):
            decrypt_refresh_token(tampered, "v1", env)
        with self.assertRaises(TokenVaultError):
            decrypt_refresh_token(encrypted["ciphertext_hex"], "missing", env)

    def test_key_rotation_reads_old_version_and_encrypts_with_current(self):
        old_key, new_key = generate_encryption_key(), generate_encryption_key()
        old_env = {"NEXUS_TOKEN_ENCRYPTION_KEY": old_key, "NEXUS_TOKEN_ENCRYPTION_KEY_VERSION": "v1"}
        encrypted = encrypt_refresh_token("rotate-me", old_env)
        keyring = {
            "NEXUS_TOKEN_ENCRYPTION_KEYS_JSON": json.dumps({"v1": old_key, "v2": new_key}),
            "NEXUS_TOKEN_ENCRYPTION_KEY_VERSION": "v2",
        }
        self.assertEqual(decrypt_refresh_token(encrypted["ciphertext_hex"], "v1", keyring), "rotate-me")
        rotated = encrypt_refresh_token("rotate-me", keyring)
        self.assertEqual(rotated["key_version"], "v2")
        self.assertEqual(decrypt_refresh_token(rotated["ciphertext_hex"], "v2", keyring), "rotate-me")

    def test_missing_or_invalid_key_material_fails_closed(self):
        with self.assertRaises(TokenVaultError):
            encrypt_refresh_token("secret", {})
        with self.assertRaises(TokenVaultError):
            encrypt_refresh_token("secret", {"NEXUS_TOKEN_ENCRYPTION_KEY": "too-short"})
        with self.assertRaises(TokenVaultError):
            encrypt_refresh_token("secret", {
                "NEXUS_TOKEN_ENCRYPTION_KEYS_JSON": "[]",
                "NEXUS_TOKEN_ENCRYPTION_KEY_VERSION": "v1",
            })


    def test_token_vault_configuration_preflight_validates_keyring(self):
        key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
        self.assertEqual(validate_token_vault_config({
            "NEXUS_TOKEN_ENCRYPTION_KEYS_JSON": json.dumps({"v1": key}),
            "NEXUS_TOKEN_ENCRYPTION_KEY_VERSION": "v1",
        }), "v1")
        with self.assertRaises(TokenVaultError):
            validate_token_vault_config({})


if __name__ == "__main__":
    unittest.main()
