from pydantic import BaseModel, EmailStr
from typing import Optional


class CardInfo(BaseModel):
    """GPT-4o Vision 擷取的名片資訊"""
    name: str
    title: Optional[str] = ""
    email: Optional[str] = ""
    company: Optional[str] = ""
    # 原始 OCR 文字（用於 debug / 手動修正）
    raw_text: Optional[str] = ""


class ScanRequest(BaseModel):
    """前端送出的掃描請求"""
    # base64 encoded image (data URL 格式，含 data:image/...;base64, 前綴)
    image_data: str
    event_name: str


class ScanResponse(BaseModel):
    """回傳給前端的名片擷取結果（供使用者確認）"""
    card: CardInfo
    event_name: str


class SendRequest(BaseModel):
    """確認後送出的寄信請求"""
    card: CardInfo
    event_name: str


class SendResponse(BaseModel):
    success: bool
    message: str
    recipient_email: Optional[str] = ""


class UserSession(BaseModel):
    """儲存在 session 的使用者資訊"""
    email: str
    name: str
    picture: Optional[str] = ""
    # Gmail OAuth2 token（加密後儲存）
    access_token: str
    refresh_token: Optional[str] = None
