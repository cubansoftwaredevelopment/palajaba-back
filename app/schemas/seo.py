from pydantic import BaseModel, Field


class SeoSitemapUrlPublic(BaseModel):
    loc: str
    lastmod: str | None = None
    changefreq: str | None = None
    priority: str | None = None


class SeoIndexableUrlsPublic(BaseModel):
    site_url: str
    urls: list[SeoSitemapUrlPublic] = Field(default_factory=list)


class SeoStorePagePublic(BaseModel):
    slug: str
    title: str
    description: str
    canonical: str
    og_image: str
    head_html: str
    body_html: str
