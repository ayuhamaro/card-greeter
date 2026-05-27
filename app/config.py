from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # AI Vision
    openai_api_key: str

    # Google OAuth2
    google_client_id: str
    google_client_secret: str

    # Session
    session_secret_key: str

    # Sender identity
    sender_name: str
    sender_bio: str

    # Access control
    allowed_email: str

    # App
    app_base_url: str = "http://localhost:8000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
