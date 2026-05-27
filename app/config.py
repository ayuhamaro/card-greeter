from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    # AI Vision
    openai_api_key: str
    openai_vision_model: str = "gpt-5.5"

    # Google OAuth2
    google_client_id: str
    google_client_secret: str

    # Session
    session_secret_key: str
    # Token 加密金鑰（Fernet 32-byte URL-safe base64）
    # 生成指令：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    session_encrypt_key: str

    # Sender identity
    sender_name: str
    sender_bio_file: str  # 路徑指向 HTML 格式的自我介紹檔案

    # Access control
    allowed_email: str

    # App
    app_base_url: str = "http://localhost:8000"

    @property
    def sender_bio(self) -> str:
        """讀取 HTML 自我介紹檔案，內容直接嵌入郵件樣板"""
        path = Path(self.sender_bio_file)
        if not path.exists():
            raise FileNotFoundError(
                f"sender_bio_file not found: {self.sender_bio_file}\n"
                f"請確認檔案存在並檢查 .env 中的 SENDER_BIO_FILE 路徑。"
            )
        return path.read_text(encoding="utf-8").strip()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # 防止 pydantic validation error 時將機密欄位值印入錯誤訊息
        hide_input_in_errors = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
