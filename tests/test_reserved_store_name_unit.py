import unittest
from unittest.mock import patch

from app.services.admins import is_admin_username
from app.services.seller_profile import _name_matches_admin


class ReservedStoreNameTests(unittest.TestCase):
    def test_admin_username_is_reserved_regardless_of_case(self) -> None:
        with patch("app.services.admins.settings") as settings:
            settings.admin_username = "admin"
            self.assertTrue(is_admin_username("admin"))
            self.assertTrue(is_admin_username(" Admin "))
            self.assertFalse(is_admin_username("Mi tienda"))

    def test_admin_username_counts_as_a_taken_store_name(self) -> None:
        with (
            patch("app.services.admins.settings") as admin_settings,
            patch("app.services.seller_profile.settings") as profile_settings,
        ):
            admin_settings.admin_username = "admin"
            profile_settings.admin_username = "admin"
            self.assertTrue(_name_matches_admin("ADMIN"))
            self.assertTrue(_name_matches_admin("admin!"))
            self.assertFalse(_name_matches_admin("Mi tienda"))


if __name__ == "__main__":
    unittest.main()
