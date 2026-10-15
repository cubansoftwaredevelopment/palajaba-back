from pydantic import BaseModel, Field

from app.utils.datetime import UtcDateTime


class BannerPublic(BaseModel):
    id: str
    image_url: str
    title: str | None = None
    link_url: str | None = None
    province_ids: list[str] = Field(default_factory=list)
    sort_order: int = 0


class BannerAdminPublic(BannerPublic):
    is_active: bool = True
    created_at: UtcDateTime | None = None
    updated_at: UtcDateTime | None = None


class BannerUpdate(BaseModel):
    title: str | None = None
    link_url: str | None = None
    province_ids: list[str] | None = None
    is_active: bool | None = None
    sort_order: int | None = None