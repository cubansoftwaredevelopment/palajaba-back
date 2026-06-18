from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_positive_int_env(value: object, *, field_name: str) -> object:
    if value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        cleaned = value.split("#", 1)[0].strip().replace("_", "")
        if not cleaned:
            raise ValueError(f"{field_name} no puede estar vacío.")
        return cleaned
    return value


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    database_name: str = "ecommerce"
    secret_key: str = "dev-secret-change-in-production"
    admin_username: str = "admin"
    admin_password: str = "admin"
    access_token_expire_minutes: int = 480
    access_token_expire_days: int | None = None
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    eltoque_api_key: str = ""
    eltoque_api_base_url: str = "https://tasas.eltoque.com"
    eltoque_user_agent: str = (
        "Mozilla/5.0 (compatible; PaLaJaba/1.0; +https://palajaba.com)"
    )
    eltoque_request_timeout_seconds: float = 20.0
    exchange_rates_refresh_seconds: int = 1200

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("access_token_expire_minutes", mode="before")
    @classmethod
    def parse_access_token_expire_minutes(cls, value: object) -> object:
        return _parse_positive_int_env(value, field_name="ACCESS_TOKEN_EXPIRE_MINUTES")

    @field_validator("access_token_expire_days", mode="before")
    @classmethod
    def parse_access_token_expire_days(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.split("#", 1)[0].strip()):
            return None
        return _parse_positive_int_env(value, field_name="ACCESS_TOKEN_EXPIRE_DAYS")

    @field_validator("access_token_expire_minutes")
    @classmethod
    def validate_access_token_expire_minutes(cls, value: int) -> int:
        if value < 1:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES debe ser al menos 1.")
        if value > 60 * 24 * 365 * 10:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRE_MINUTES es demasiado alto (máximo ~10 años)."
            )
        return value

    @field_validator("access_token_expire_days")
    @classmethod
    def validate_access_token_expire_days(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1:
            raise ValueError("ACCESS_TOKEN_EXPIRE_DAYS debe ser al menos 1.")
        if value > 365 * 10:
            raise ValueError("ACCESS_TOKEN_EXPIRE_DAYS es demasiado alto (máximo 10 años).")
        return value

    @property
    def effective_access_token_expire_minutes(self) -> int:
        if self.access_token_expire_days is not None:
            return self.access_token_expire_days * 24 * 60
        return self.access_token_expire_minutes

    @property
    def cors_origins_list(self) -> list[str]:
        origins: list[str] = []
        for origin in self.cors_origins.split(","):
            normalized = origin.strip().strip('"').strip("'").rstrip("/")
            if normalized:
                origins.append(normalized)
        return origins

    @property
    def cloudinary_enabled(self) -> bool:
        return bool(
            self.cloudinary_cloud_name.strip()
            and self.cloudinary_api_key.strip()
            and self.cloudinary_api_secret.strip()
        )


settings = Settings()
