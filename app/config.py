from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Ctrl+teach"
    database_url: str = "sqlite:///./ctrlteach.db"
    jwt_secret: str
    jwt_expire_minutes: int = 60


settings = Settings()
