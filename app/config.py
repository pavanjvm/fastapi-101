from pydantic_settings import BaseSettings, SettiungsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf=8",
        extra = "ignore", 
    )
    database_url: str = "sqlite:///./ctrlteach.db"

settings =  Settings()