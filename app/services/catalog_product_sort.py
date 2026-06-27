from typing import Any, Literal

from app.services.product_popularity import MARKETPLACE_PRODUCT_SORT
from app.utils.currency_conversion import convert_amount

ProductSortMode = Literal["popularity", "price", "alphabetical", "manual"]
DEFAULT_PRODUCT_SORT_MODE: ProductSortMode = "popularity"
PRICE_SORT_REFERENCE_CURRENCY = "CUP"

PRODUCT_SORT_MODES: tuple[ProductSortMode, ...] = (
    "popularity",
    "price",
    "alphabetical",
    "manual",
)


def normalize_product_sort_mode(value: str | None) -> ProductSortMode:
    if value in PRODUCT_SORT_MODES:
        return value  # type: ignore[return-value]
    return DEFAULT_PRODUCT_SORT_MODE


def product_price_in_reference_currency(doc: dict[str, Any]) -> float:
    amount = float(doc.get("base_price") or 0)
    currency = str(doc.get("base_currency") or "CUP").upper()
    if currency == PRICE_SORT_REFERENCE_CURRENCY:
        return amount
    return convert_amount(amount, currency, PRICE_SORT_REFERENCE_CURRENCY)


def product_price_sort_key(doc: dict[str, Any]) -> tuple[float, str]:
    return (
        product_price_in_reference_currency(doc),
        str(doc.get("name") or "").lower(),
    )


def uses_in_memory_product_sort(mode: str | None) -> bool:
    return normalize_product_sort_mode(mode) == "price"


def mongo_sort_for_product_mode(mode: str | None) -> list[tuple[str, int]] | None:
    normalized = normalize_product_sort_mode(mode)
    if normalized == "price":
        return None
    if normalized == "alphabetical":
        return [("name", 1), ("sort_order", 1)]
    if normalized == "manual":
        return [("sort_order", 1), ("name", 1)]
    return MARKETPLACE_PRODUCT_SORT


def sort_product_docs(docs: list[dict[str, Any]], mode: str | None) -> list[dict[str, Any]]:
    normalized = normalize_product_sort_mode(mode)
    if normalized == "price":
        return sorted(docs, key=product_price_sort_key)
    if normalized == "alphabetical":
        return sorted(docs, key=lambda doc: str(doc.get("name") or "").lower())
    if normalized == "manual":
        return sorted(
            docs,
            key=lambda doc: (int(doc.get("sort_order") or 0), str(doc.get("name") or "").lower()),
        )
    return sorted(
        docs,
        key=lambda doc: (
            -int(doc.get("popularity") or 0),
            int(doc.get("sort_order") or 0),
            str(doc.get("name") or "").lower(),
        ),
    )
