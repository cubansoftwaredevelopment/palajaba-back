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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def cloudinary_enabled(self) -> bool:
        return bool(
            self.cloudinary_cloud_name.strip()
            and self.cloudinary_api_key.strip()
            and self.cloudinary_api_secret.strip()
        )


settings = Settings()
