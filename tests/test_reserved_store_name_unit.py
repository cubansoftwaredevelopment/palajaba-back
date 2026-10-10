import unittest
from unittest.mock import patch

from app.services.admins import is_admin_username


class ReservedStoreNameTests(unittest.TestCase):
    def test_admin_username_is_reserved_regardless_of_case(self) -> None:
        with patch("app.services.admins.settings") as settings:
            settings.admin_username = "admin"
            self.assertTrue(is_admin_username("admin"))
            self.assertTrue(is_admin_username(" Admin "))
            self.assertFalse(is_admin_username("Mi tienda"))


if __name__ == "__main__":
    unittest.main()
