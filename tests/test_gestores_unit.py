from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.schemas.gestores import (
    GestorCatalogAccess,
    GestorCatalogAccessUpdate,
    GestorCheckoutPhones,
    GestorCheckoutPhonesUpdate,
    GestorCreateRequest,
    GestorSelectedProduct,
    GestorSelectedProductsUpdate,
    GestorSetupRequest,
)
from app.services.gestores import (
    build_gestor_document,
    compute_gestor_display_price,
    default_gestor_catalog_access,
    gestor_catalog_access_to_document,
    normalize_gestor_username,
    parse_checkout_gestor_ids,
    parse_checkout_include_store_phone,
    parse_gestor_catalog_access,
    parse_selected_products,
    product_is_allowed_for_gestores,
    selected_products_to_document,
    validate_gestor_username,
)


class GestorUsernameHelpersTests(unittest.TestCase):
    def test_normalize_username_lowercases_and_trims(self) -> None:
        self.assertEqual(normalize_gestor_username("  Ana_Maria "), "ana_maria")

    def test_validate_username_accepts_slug_friendly(self) -> None:
        self.assertEqual(validate_gestor_username("pepe-ventas"), "pepe-ventas")
        self.assertEqual(validate_gestor_username("venta_01"), "venta_01")

    def test_validate_username_rejects_invalid(self) -> None:
        with self.assertRaises(ValueError):
            validate_gestor_username("-pepe")
        with self.assertRaises(ValueError):
            validate_gestor_username("pepe-")
        with self.assertRaises(ValueError):
            validate_gestor_username("pe pe")
        with self.assertRaises(ValueError):
            validate_gestor_username("a")
        with self.assertRaises(ValueError):
            validate_gestor_username("pepe!")


class GestorPriceHelpersTests(unittest.TestCase):
    def test_display_price_adds_margin_same_currency(self) -> None:
        self.assertEqual(compute_gestor_display_price(2500, 300), 2800.0)

    def test_display_price_clamps_negative_inputs(self) -> None:
        self.assertEqual(compute_gestor_display_price(-10, 5), 5.0)
        self.assertEqual(compute_gestor_display_price(100, -20), 100.0)

    def test_display_price_rounds_to_two_decimals(self) -> None:
        self.assertEqual(compute_gestor_display_price(10.555, 0.111), 10.67)


class GestorCatalogAccessHelpersTests(unittest.TestCase):
    def test_default_access_is_selected_empty(self) -> None:
        access = default_gestor_catalog_access()
        self.assertEqual(access.mode, "selected")
        self.assertEqual(access.product_ids, [])

    def test_parse_access_mode_all_clears_ids(self) -> None:
        access = parse_gestor_catalog_access({"mode": "all", "product_ids": ["a", "b"]})
        self.assertEqual(access.mode, "all")
        self.assertEqual(access.product_ids, [])

    def test_product_allowed_for_all_mode(self) -> None:
        access = GestorCatalogAccess(mode="all", product_ids=[])
        self.assertTrue(product_is_allowed_for_gestores(access, "any-id"))

    def test_product_allowed_for_selected_mode(self) -> None:
        access = GestorCatalogAccess(mode="selected", product_ids=["p1", "p2"])
        self.assertTrue(product_is_allowed_for_gestores(access, "p1"))
        self.assertFalse(product_is_allowed_for_gestores(access, "p3"))

    def test_access_to_document(self) -> None:
        doc = gestor_catalog_access_to_document(
            GestorCatalogAccess(mode="selected", product_ids=["x", "y"])
        )
        self.assertEqual(doc, {"mode": "selected", "product_ids": ["x", "y"]})


class GestorSelectedProductsHelpersTests(unittest.TestCase):
    def test_parse_selected_products_dedupes_and_clamps(self) -> None:
        products = parse_selected_products(
            [
                {"product_id": "a", "margin_amount": 10},
                {"product_id": "a", "margin_amount": 99},
                {"product_id": "b", "margin_amount": -5},
            ]
        )
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].product_id, "a")
        self.assertEqual(products[0].margin_amount, 10)
        self.assertEqual(products[1].margin_amount, 0)

    def test_selected_products_roundtrip_document(self) -> None:
        products = [GestorSelectedProduct(product_id="p1", margin_amount=12.5)]
        raw = selected_products_to_document(products)
        self.assertEqual(raw, [{"product_id": "p1", "margin_amount": 12.5}])


class GestorSchemaValidationTests(unittest.TestCase):
    def test_create_request_requires_username(self) -> None:
        with self.assertRaises(ValidationError):
            GestorCreateRequest(username="")

    def test_setup_request_normalizes_phone(self) -> None:
        setup = GestorSetupRequest(
            setup_token="x" * 20,
            password="secreto1",
            phone="+53 5 123 4567",
        )
        self.assertEqual(setup.phone, "51234567")

    def test_selected_products_update_rejects_duplicates(self) -> None:
        with self.assertRaises(ValidationError):
            GestorSelectedProductsUpdate(
                products=[
                    GestorSelectedProduct(product_id="p1", margin_amount=1),
                    GestorSelectedProduct(product_id="p1", margin_amount=2),
                ]
            )

    def test_catalog_access_update_all_clears_ids(self) -> None:
        update = GestorCatalogAccessUpdate(mode="all", product_ids=["a"])
        self.assertEqual(update.product_ids, [])

    def test_checkout_phones_dedupes_ids(self) -> None:
        phones = GestorCheckoutPhones(gestor_ids=["a", " a ", "b", "a"])
        self.assertEqual(phones.gestor_ids, ["a", "b"])
        self.assertTrue(phones.include_store_phone)

    def test_checkout_phones_update_schema(self) -> None:
        update = GestorCheckoutPhonesUpdate(gestor_ids=["g1", "g1", ""], include_store_phone=False)
        self.assertEqual(update.gestor_ids, ["g1"])
        self.assertFalse(update.include_store_phone)

    def test_checkout_phones_rejects_empty_selection(self) -> None:
        with self.assertRaises(ValidationError):
            GestorCheckoutPhones(gestor_ids=[], include_store_phone=False)
        with self.assertRaises(ValidationError):
            GestorCheckoutPhonesUpdate(gestor_ids=[], include_store_phone=False)


class GestorCheckoutPhonesHelpersTests(unittest.TestCase):
    def test_parse_checkout_gestor_ids_defaults(self) -> None:
        self.assertEqual(parse_checkout_gestor_ids(None), [])
        self.assertEqual(parse_checkout_gestor_ids("bad"), [])

    def test_parse_checkout_gestor_ids_list(self) -> None:
        self.assertEqual(parse_checkout_gestor_ids(["x", "x", " y "]), ["x", "y"])

    def test_parse_checkout_include_store_phone(self) -> None:
        self.assertTrue(parse_checkout_include_store_phone(None))
        self.assertTrue(parse_checkout_include_store_phone(True))
        self.assertFalse(parse_checkout_include_store_phone(False))


class GestorDocumentBuilderTests(unittest.TestCase):
    def test_build_gestor_document_pending_credentials(self) -> None:
        from bson import ObjectId

        seller_id = ObjectId()
        doc = build_gestor_document(seller_id=seller_id, username="  Maria_Venta ")
        self.assertEqual(doc["username"], "maria_venta")
        self.assertEqual(doc["seller_id"], seller_id)
        self.assertIsNone(doc["password_hash"])
        self.assertIsNone(doc["phone"])
        self.assertEqual(doc["selected_products"], [])


if __name__ == "__main__":
    unittest.main()
