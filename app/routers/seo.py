from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.config import settings
from app.schemas.seo import SeoIndexableUrlsPublic
from app.services import seo as seo_service

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
