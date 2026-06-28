from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse, Response

from app.config import settings
from app.schemas.seo import SeoIndexableUrlsPublic, SeoStorePagePublic
from app.services import seo as seo_service
from app.services import seo_store_page as seo_store_page_service

router = APIRouter(prefix="/api/platform/seo", tags=["seo"])


@router.get("/indexable-urls", response_model=SeoIndexableUrlsPublic)
async def get_indexable_urls():
    store_entries = await seo_service.list_indexable_store_entries()
    urls = seo_service.build_sitemap_url_entries(settings.public_site_url, store_entries)
    return SeoIndexableUrlsPublic(site_url=settings.public_site_url, urls=urls)


@router.get("/sitemap.xml")
async def get_sitemap_xml():
    store_entries = await seo_service.list_indexable_store_entries()
    xml = seo_service.build_sitemap_xml(settings.public_site_url, store_entries)
    return Response(content=xml, media_type="application/xml; charset=utf-8")


@router.get("/robots.txt", response_class=PlainTextResponse)
async def get_robots_txt():
    site_url = settings.public_site_url.rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /tienda",
        "Disallow: /login",
        "Disallow: /registro/pago",
        "Disallow: /registro/verificacion",
        "Disallow: /registro/exito",
        "",
        f"Sitemap: {site_url}/sitemap.xml",
    ]
    return "\n".join(lines) + "\n"


@router.get("/store/{store_slug}", response_model=SeoStorePagePublic)
async def get_store_seo_page(store_slug: str):
    try:
        catalog = await seo_store_page_service.load_seo_store_catalog(store_slug)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    site_url = settings.public_site_url
    return SeoStorePagePublic(
        slug=catalog.store.store_slug,
        title=seo_store_page_service.build_store_page_title(catalog),
        description=seo_store_page_service.build_store_meta_description(catalog),
        canonical=seo_store_page_service.build_store_canonical_url(site_url, catalog.store.store_slug),
        og_image=catalog.store.profile_photo_url or f"{site_url.rstrip('/')}/logo.png",
        head_html=seo_store_page_service.build_store_head_html(catalog, site_url=site_url),
        body_html=seo_store_page_service.build_store_body_html(catalog),
    )


@router.get("/store/{store_slug}.html")
async def get_store_seo_html(store_slug: str):
    try:
        html = await seo_store_page_service.build_store_page_document(
            store_slug,
            site_url=settings.public_site_url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return Response(content=html, media_type="text/html; charset=utf-8")
