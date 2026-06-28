from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from app.database import get_registrations_collection
from app.services.seller_profile import is_profile_complete
from app.services.subscriptions import is_subscription_active
from app.utils.reserved_store_slugs import is_reserved_store_slug
from app.utils.store_slug import store_name_to_slug

STATIC_SITEMAP_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("", "daily", "1.0"),
    ("comprar", "daily", "0.9"),
    ("aplicacion", "monthly", "0.6"),
    ("registro", "monthly", "0.7"),
)


def _normalize_site_url(site_url: str) -> str:
    return site_url.strip().rstrip("/")


def _format_lastmod(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()[:10]
    return None


async def list_indexable_store_entries() -> list[dict[str, Any]]:
    collection = get_registrations_collection()
    cursor = collection.find(
        {
            "status": "approved",
            "phone": {"$exists": True, "$nin": [None, ""]},
        },
        {
            "store_slug": 1,
            "store_name": 1,
            "updated_at": 1,
            "profile_photo_url": 1,
            "category_ids": 1,
            "offers_delivery": 1,
            "business_area": 1,
            "subscription_starts_at": 1,
            "subscription_ends_at": 1,
        },
    )

    entries: list[dict[str, Any]] = []
    async for doc in cursor:
        if not is_subscription_active(doc) or not is_profile_complete(doc):
            continue

        slug = doc.get("store_slug") or store_name_to_slug(str(doc.get("store_name", "")))
        if is_reserved_store_slug(slug):
            continue

        entries.append(
            {
                "slug": slug,
                "lastmod": _format_lastmod(doc.get("updated_at")),
            }
        )

    entries.sort(key=lambda item: item["slug"])
    return entries


def build_sitemap_url_entries(
    site_url: str,
    store_entries: list[dict[str, Any]],
) -> list[dict[str, str | None]]:
    base = _normalize_site_url(site_url)
    urls: list[dict[str, str | None]] = []

    for path, changefreq, priority in STATIC_SITEMAP_ENTRIES:
        loc = base if not path else f"{base}/{path}"
        urls.append(
            {
                "loc": loc,
                "lastmod": None,
                "changefreq": changefreq,
                "priority": priority,
            }
        )

    for entry in store_entries:
        urls.append(
            {
                "loc": f"{base}/{entry['slug']}",
                "lastmod": entry.get("lastmod"),
                "changefreq": "weekly",
                "priority": "0.8",
            }
        )

    return urls


def build_sitemap_xml(site_url: str, store_entries: list[dict[str, Any]]) -> str:
    url_entries = build_sitemap_url_entries(site_url, store_entries)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for entry in url_entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(str(entry['loc']))}</loc>")
        if entry.get("lastmod"):
            lines.append(f"    <lastmod>{escape(str(entry['lastmod']))}</lastmod>")
        if entry.get("changefreq"):
            lines.append(f"    <changefreq>{escape(str(entry['changefreq']))}</changefreq>")
        if entry.get("priority"):
            lines.append(f"    <priority>{escape(str(entry['priority']))}</priority>")
        lines.append("  </url>")

    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
