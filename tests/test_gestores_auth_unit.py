from __future__ import annotations

import unittest

from app.security import (
    create_gestor_setup_token,
    create_gestor_token,
    decode_gestor_setup_token,
    decode_gestor_token,
    decode_seller_token,
    hash_password,
    verify_password,
)


class GestorTokenUnitTests(unittest.TestCase):
    def test_gestor_token_roundtrip(self) -> None:
        token = create_gestor_token(
            gestor_id="gid1",
            seller_id="sid1",
            username="pepe",
        )
        payload = decode_gestor_token(token)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["role"], "gestor")
        self.assertEqual(payload["gestor_id"], "gid1")
        self.assertEqual(payload["seller_id"], "sid1")
        self.assertEqual(payload["username"], "pepe")

    def test_gestor_token_not_accepted_as_seller(self) -> None:
        token = create_gestor_token(gestor_id="g", seller_id="s", username="u")
        self.assertIsNone(decode_seller_token(token))

    def test_setup_token_roundtrip(self) -> None:
        token = create_gestor_setup_token(
            gestor_id="gid1",
            seller_id="sid1",
            username="pepe",
            store_name="Mi Tienda",
        )
        payload = decode_gestor_setup_token(token)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["role"], "gestor_setup")
        self.assertEqual(payload["store_name"], "Mi Tienda")
        self.assertIsNone(decode_gestor_token(token))

    def test_password_hash_verify(self) -> None:
        hashed = hash_password("secreto123")
        self.assertTrue(verify_password("secreto123", hashed))
        self.assertFalse(verify_password("otra", hashed))


if __name__ == "__main__":
    unittest.main()
