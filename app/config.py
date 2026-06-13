from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    database_name: str = "ecommerce"
    secret_key: str = "dev-secret-change-in-production"
    admin_username: str = "admin"
    admin_password: str = "admin"
    access_token_expire_minutes: int = 480
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
    exchange_rates_refresh_seconds: int = 3600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
