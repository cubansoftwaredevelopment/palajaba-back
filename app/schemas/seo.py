from pydantic import BaseModel, Field


class SeoSitemapUrlPublic(BaseModel):
    loc: str
    lastmod: str | None = None
    changefreq: str | None = None
    priority: str | None = None


class SeoIndexableUrlsPublic(BaseModel):
    site_url: str
    urls: list[SeoSitemapUrlPublic] = Field(default_factory=list)
