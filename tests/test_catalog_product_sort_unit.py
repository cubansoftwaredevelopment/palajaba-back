from __future__ import annotations



import unittest



from app.services import exchange_rates as exchange_rates_service

from app.services.catalog_product_sort import (

    DEFAULT_PRODUCT_SORT_MODE,

    mongo_sort_for_product_mode,

    normalize_product_sort_mode,

    product_price_in_reference_currency,

    sort_product_docs,

    uses_in_memory_product_sort,

)

from app.services.product_popularity import MARKETPLACE_PRODUCT_SORT





def _set_test_exchange_rates() -> None:

    exchange_rates_service._cup_per_unit_cache.update(

        {"CUP": 1.0, "USD": 655.0, "EUR": 750.0, "MLC": 440.0},

    )

    exchange_rates_service._rates_available = True





def _reset_exchange_rates() -> None:

    exchange_rates_service._cup_per_unit_cache = {"CUP": 1.0}

    exchange_rates_service._rates_available = False





class NormalizeProductSortModeTests(unittest.TestCase):

    def test_defaults_to_popularity_when_missing(self) -> None:

        self.assertEqual(normalize_product_sort_mode(None), "popularity")

        self.assertEqual(normalize_product_sort_mode(""), "popularity")

        self.assertEqual(normalize_product_sort_mode("unknown"), "popularity")



    def test_accepts_valid_modes(self) -> None:

        for mode in ("popularity", "price", "alphabetical", "manual"):

            self.assertEqual(normalize_product_sort_mode(mode), mode)



    def test_default_constant_is_popularity(self) -> None:

        self.assertEqual(DEFAULT_PRODUCT_SORT_MODE, "popularity")





class MongoSortForProductModeTests(unittest.TestCase):

    def test_popularity_uses_marketplace_sort(self) -> None:

        self.assertEqual(mongo_sort_for_product_mode("popularity"), MARKETPLACE_PRODUCT_SORT)

        self.assertEqual(mongo_sort_for_product_mode(None), MARKETPLACE_PRODUCT_SORT)



    def test_price_sort_uses_in_memory_ordering(self) -> None:

        self.assertIsNone(mongo_sort_for_product_mode("price"))

        self.assertTrue(uses_in_memory_product_sort("price"))



    def test_alphabetical_sort(self) -> None:

        self.assertEqual(

            mongo_sort_for_product_mode("alphabetical"),

            [("name", 1), ("sort_order", 1)],

        )



    def test_manual_sort(self) -> None:

        self.assertEqual(mongo_sort_for_product_mode("manual"), [("sort_order", 1), ("name", 1)])





class SortProductDocsTests(unittest.TestCase):

    @classmethod

    def setUpClass(cls) -> None:

        _set_test_exchange_rates()

        cls.products = [

            {

                "name": "Zeta",

                "base_price": 300.0,

                "base_currency": "CUP",

                "popularity": 5,

                "sort_order": 2,

            },

            {

                "name": "Alpha",

                "base_price": 100.0,

                "base_currency": "CUP",

                "popularity": 20,

                "sort_order": 0,

            },

            {

                "name": "Beta",

                "base_price": 200.0,

                "base_currency": "CUP",

                "popularity": 20,

                "sort_order": 1,

            },

        ]



    @classmethod

    def tearDownClass(cls) -> None:

        _reset_exchange_rates()



    def test_popularity_desc_then_sort_order_then_name(self) -> None:

        ordered = sort_product_docs(self.products, "popularity")

        self.assertEqual([item["name"] for item in ordered], ["Alpha", "Beta", "Zeta"])



    def test_price_asc_then_name_for_same_currency(self) -> None:

        ordered = sort_product_docs(self.products, "price")

        self.assertEqual([item["name"] for item in ordered], ["Alpha", "Beta", "Zeta"])



    def test_price_converts_mixed_currencies_to_cup(self) -> None:

        docs = [

            {"name": "Caro USD", "base_price": 10.0, "base_currency": "USD"},

            {"name": "Barato CUP", "base_price": 500.0, "base_currency": "CUP"},

            {"name": "Medio USD", "base_price": 1.0, "base_currency": "USD"},

        ]

        ordered = sort_product_docs(docs, "price")

        self.assertEqual([item["name"] for item in ordered], ["Barato CUP", "Medio USD", "Caro USD"])

        self.assertEqual(product_price_in_reference_currency(docs[0]), 6550.0)

        self.assertEqual(product_price_in_reference_currency(docs[2]), 655.0)



    def test_alphabetical_by_name(self) -> None:

        ordered = sort_product_docs(self.products, "alphabetical")

        self.assertEqual([item["name"] for item in ordered], ["Alpha", "Beta", "Zeta"])



    def test_manual_by_sort_order(self) -> None:

        ordered = sort_product_docs(self.products, "manual")

        self.assertEqual([item["name"] for item in ordered], ["Alpha", "Beta", "Zeta"])



    def test_missing_fields_use_safe_defaults(self) -> None:

        docs = [{"name": "Solo nombre"}, {"name": "Otro", "popularity": 1}]

        ordered = sort_product_docs(docs, "popularity")

        self.assertEqual([item["name"] for item in ordered], ["Otro", "Solo nombre"])


