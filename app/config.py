import json
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    # AI Vision (OpenAI)
    openai_api_key: str
    openai_vision_model: str = "gpt-5.5"
    openai_collab_model: str = "gpt-5.5"

    # Gemini (company lookup with Grounding)
    gemini_api_key: str
    gemini_grounding_model: str = "gemini-2.5-flash"

    # Google OAuth2
    google_client_id: str
    google_client_secret: str

    # Session
    session_secret_key: str
    session_encrypt_key: str

    # Sender identity
    sender_name: str
    sender_bio_file: str
    sender_line_id: str = ""

    # Collaboration hints YAML (not in repo)
    collaboration_hints_file: str

    # Access control
    allowed_email: str

    # Google Cloud Pub/Sub
    pubsub_enabled: bool = False
    google_sa_credentials_json: str = ""  # Service Account JSON 內容（非檔案路徑）
    pubsub_project_id: str = ""
    pubsub_topic_id: str = ""

    @field_validator("google_sa_credentials_json")
    @classmethod
    def validate_sa_credentials(cls, v: str) -> str:
        if not v:
            return v
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"GOOGLE_SA_CREDENTIALS_JSON is not valid JSON: {e}")
        if parsed.get("type") != "service_account":
            raise ValueError('GOOGLE_SA_CREDENTIALS_JSON must have "type": "service_account"')
        return v

    # App
    app_base_url: str = "http://localhost:8000"

    # 郵件 Footer GitHub Repo 連結
    github_repo_url: str = "https://github.com/ayuhamaro/card-greeter"

    @property
    def sender_bio(self) -> str:
        path = Path(self.sender_bio_file)
        if not path.exists():
            raise FileNotFoundError(
                f"sender_bio_file not found: {self.sender_bio_file}\n"
                "Please check SENDER_BIO_FILE in .env"
            )
        return path.read_text(encoding="utf-8").strip()

    @property
    def collaboration_hints(self) -> str:
        path = Path(self.collaboration_hints_file)
        if not path.exists():
            raise FileNotFoundError(
                f"collaboration_hints_file not found: {self.collaboration_hints_file}\n"
                "Please check COLLABORATION_HINTS_FILE in .env"
            )
        return path.read_text(encoding="utf-8").strip()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        hide_input_in_errors = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
