import unittest

from bson import ObjectId

from app.services.catalog import (
    ORDERED_PRODUCT_PREVIEW_LIMIT,
    ORDERED_PRODUCT_SEARCH_LIMIT,
    ordered_product_search_filter,
    ordered_product_search_limit,
    parse_ordered_product_ids,
)


class OrderedProductSearchTests(unittest.TestCase):
    def test_parse_skips_invalid_ids_and_duplicates(self) -> None:
        product_id = ObjectId()
        parsed = parse_ordered_product_ids([str(product_id), str(product_id), "no-es-un-id", None])
        self.assertEqual(parsed, [product_id])

    def test_empty_order_history_does_not_build_a_query(self) -> None:
        self.assertIsNone(ordered_product_search_filter("seller", [], "", []))

    def test_blank_query_lists_available_ordered_products(self) -> None:
        product_id = ObjectId()
        product_filter = ordered_product_search_filter("seller", [product_id], "  ", [])
        self.assertEqual(
            product_filter,
            {
                "seller_id": "seller",
                "_id": {"$in": [product_id]},
                "is_available": True,
                "view_only": {"$ne": True},
            },
        )
        self.assertEqual(ordered_product_search_limit("  "), ORDERED_PRODUCT_PREVIEW_LIMIT)

    def test_query_is_case_insensitive_and_escaped(self) -> None:
        product_id = ObjectId()
        category_id = ObjectId()
        product_filter = ordered_product_search_filter("seller", [product_id], "arroz.", [category_id])
        regex = product_filter["$or"][0]["name"]["$regex"]
        self.assertEqual(regex, r"arroz\.")
        self.assertEqual(product_filter["$or"][0]["name"]["$options"], "i")
        self.assertEqual(product_filter["$or"][1], {"category_id": {"$in": [category_id]}})
        self.assertEqual(product_filter["_id"], {"$in": [product_id]})
        self.assertEqual(ordered_product_search_limit("arroz."), ORDERED_PRODUCT_SEARCH_LIMIT)

    def test_query_without_categories_matches_only_the_name(self) -> None:
        product_id = ObjectId()
        product_filter = ordered_product_search_filter("seller", [product_id], "aceite", [])
        self.assertEqual(len(product_filter["$or"]), 1)
        self.assertIn("name", product_filter["$or"][0])


if __name__ == "__main__":
    unittest.main()
