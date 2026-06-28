from __future__ import annotations

import json
import re
from html import escape
from typing import Any

from app.schemas.marketplace import MarketplaceStoreCatalogPublic
from app.services.marketplace import get_store_catalog, _parse_business_area, _resolve_store_catalog_seller
from app.utils.reserved_store_slugs import is_reserved_store_slug

SEO_PRODUCTS_PER_CATEGORY = 30
SEO_DESCRIPTION_MAX_LENGTH = 160


def _normalize_site_url(site_url: str) -> str:
    return site_url.strip().rstrip("/")


def _truncate(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _format_price(amount: float, currency: str) -> str:
    rounded = int(amount) if float(amount).is_integer() else round(float(amount), 2)
    return f"{rounded} {currency.upper()}"


def _store_location_label(catalog: MarketplaceStoreCatalogPublic) -> str | None:
    area = catalog.business_area
    if area is None:
        return None
    return f"{area.municipality_name}, {area.province_name}"


def build_store_meta_description(catalog: MarketplaceStoreCatalogPublic) -> str:
    store_name = catalog.store.store_name
    location = _store_location_label(catalog)
    biography = (catalog.biography or "").strip()

    if biography:
        base = _truncate(biography, SEO_DESCRIPTION_MAX_LENGTH)
    elif catalog.total_products > 0:
        base = (
            f"Catálogo de {store_name} en Pa' La Jaba. "
            f"{catalog.total_products} productos disponibles."
        )
    else:
        base = f"Tienda {store_name} en Pa' La Jaba. Explora su catálogo y pide por WhatsApp."

    if location and location not in base:
        suffix = f" Ubicación: {location}."
        room = SEO_DESCRIPTION_MAX_LENGTH - len(suffix)
        if room > 40:
            base = _truncate(base, room) + suffix

    return _truncate(base, SEO_DESCRIPTION_MAX_LENGTH)


def build_store_page_title(catalog: MarketplaceStoreCatalogPublic) -> str:
    return f"{catalog.store.store_name} | Catálogo en Pa' La Jaba"


def build_store_canonical_url(site_url: str, slug: str) -> str:
    return f"{_normalize_site_url(site_url)}/{slug}"


def build_store_json_ld(
    catalog: MarketplaceStoreCatalogPublic,
    *,
    site_url: str,
) -> list[dict[str, Any]]:
    canonical = build_store_canonical_url(site_url, catalog.store.store_slug)
    store_block: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Store",
        "name": catalog.store.store_name,
        "url": canonical,
        "description": build_store_meta_description(catalog),
    }

    if catalog.store.profile_photo_url:
        store_block["image"] = catalog.store.profile_photo_url

    if catalog.business_area is not None:
        store_block["address"] = {
            "@type": "PostalAddress",
            "addressLocality": catalog.business_area.municipality_name,
            "addressRegion": catalog.business_area.province_name,
            "addressCountry": "CU",
        }

    products: list[dict[str, Any]] = []
    position = 1
    for section in catalog.sections:
        for product in section.products[:SEO_PRODUCTS_PER_CATEGORY]:
            item: dict[str, Any] = {
                "@type": "Product",
                "name": product.name,
                "image": product.image_url,
                "offers": {
                    "@type": "Offer",
                    "price": product.base_price,
                    "priceCurrency": product.base_currency.upper(),
                    "availability": "https://schema.org/InStock"
                    if product.is_available and not product.view_only
                    else "https://schema.org/OutOfStock",
                },
            }
            if product.description:
                item["description"] = _truncate(product.description, 240)
            products.append(
                {
                    "@type": "ListItem",
                    "position": position,
                    "item": item,
                }
            )
            position += 1

    blocks: list[dict[str, Any]] = [store_block]
    if products:
        blocks.append(
            {
                "@context": "https://schema.org",
                "@type": "ItemList",
                "name": f"Productos de {catalog.store.store_name}",
                "numberOfItems": len(products),
                "itemListElement": products,
            }
        )
    return blocks


def build_store_body_html(catalog: MarketplaceStoreCatalogPublic) -> str:
    store = catalog.store
    location = _store_location_label(catalog)
    lines: list[str] = [
        '<article class="seo-store-page">',
        f"  <header><h1>{escape(store.store_name)}</h1>",
    ]

    if catalog.biography:
        lines.append(f"  <p>{escape(catalog.biography.strip())}</p>")

    if location:
        lines.append(f"  <p><strong>Ubicación:</strong> {escape(location)}</p>")

    if catalog.categories:
        category_names = ", ".join(category.name for category in catalog.categories)
        lines.append(f"  <p><strong>Categorías:</strong> {escape(category_names)}</p>")

    lines.append(
        f"  <p>Catálogo en <a href=\"https://palajaba.com\">Pa' La Jaba</a>. "
        "Pide por WhatsApp.</p>"
    )
    lines.append("  </header>")

    if not catalog.sections:
        lines.append("  <p>Esta tienda aún no tiene productos publicados.</p>")
    else:
        for section in catalog.sections:
            lines.append(f"  <section><h2>{escape(section.category_name)}</h2><ul>")
            for product in section.products[:SEO_PRODUCTS_PER_CATEGORY]:
                price = _format_price(product.base_price, product.base_currency)
                status_bits = []
                if not product.is_available:
                    status_bits.append("Agotado")
                if product.view_only:
                    status_bits.append("Solo consulta")
                status = f" ({', '.join(status_bits)})" if status_bits else ""
                lines.append(
                    "    <li>"
                    f"<strong>{escape(product.name)}</strong> — {escape(price)}{escape(status)}"
                    "</li>"
                )
            lines.append("  </ul></section>")

    lines.append("</article>")
    return "\n".join(lines)


def build_store_head_html(
    catalog: MarketplaceStoreCatalogPublic,
    *,
    site_url: str,
) -> str:
    title = build_store_page_title(catalog)
    description = build_store_meta_description(catalog)
    canonical = build_store_canonical_url(site_url, catalog.store.store_slug)
    og_image = catalog.store.profile_photo_url or f"{_normalize_site_url(site_url)}/logo.png"
    json_ld_blocks = build_store_json_ld(catalog, site_url=site_url)

    lines = [
        f"<title>{escape(title)}</title>",
        f'<meta name="description" content="{escape(description)}" />',
        '<meta name="robots" content="index, follow" />',
        f'<link rel="canonical" href="{escape(canonical)}" />',
        '<meta property="og:type" content="website" />',
        '<meta property="og:site_name" content="Pa\' La Jaba" />',
        f'<meta property="og:url" content="{escape(canonical)}" />',
        f'<meta property="og:title" content="{escape(title)}" />',
        f'<meta property="og:description" content="{escape(description)}" />',
        f'<meta property="og:image" content="{escape(og_image)}" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{escape(title)}" />',
        f'<meta name="twitter:description" content="{escape(description)}" />',
        f'<meta name="twitter:image" content="{escape(og_image)}" />',
    ]

    for block in json_ld_blocks:
        lines.append(
            f'<script type="application/ld+json">{json.dumps(block, ensure_ascii=False)}</script>'
        )

    return "\n    ".join(lines)


async def load_seo_store_catalog(store_slug: str) -> MarketplaceStoreCatalogPublic:
    if is_reserved_store_slug(store_slug):
        raise ValueError("Tienda no válida.")

    seller = await _resolve_store_catalog_seller(store_slug)
    business_area = _parse_business_area(seller.get("business_area"))
    if business_area is None:
        raise ValueError("La tienda no tiene ubicación publicada.")

    return await get_store_catalog(
        store_slug,
        business_area.province_id,
        business_area.municipality_id,
        limit_per_category=SEO_PRODUCTS_PER_CATEGORY,
    )


async def build_store_page_document(
    store_slug: str,
    *,
    site_url: str,
    asset_tags: str = "",
) -> str:
    catalog = await load_seo_store_catalog(store_slug)
    head = build_store_head_html(catalog, site_url=site_url)
    body = build_store_body_html(catalog)

    return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" type="image/png" href="/logo.png" />
    <style>
      .seo-store-page {{ max-width: 42rem; margin: 0 auto; padding: 1.25rem; font-family: Georgia, serif; color: #2d5016; line-height: 1.5; }}
      .seo-store-page h1 {{ font-size: 1.75rem; margin-bottom: 0.5rem; }}
      .seo-store-page h2 {{ font-size: 1.15rem; margin-top: 1.5rem; }}
      .seo-store-page ul {{ padding-left: 1.25rem; }}
      .seo-store-page li {{ margin: 0.35rem 0; }}
    </style>
    {head}
    {asset_tags}
  </head>
  <body>
    {body}
    <div id="root"></div>
  </body>
</html>
"""
