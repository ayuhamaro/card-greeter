from pydantic import BaseModel
from typing import Optional


class AddressInfo(BaseModel):
    street: Optional[str] = ""
    city: Optional[str] = ""
    region: Optional[str] = ""
    postal_code: Optional[str] = ""
    country: Optional[str] = ""


class CardInfo(BaseModel):
    name: str
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    title: Optional[str] = ""
    email: Optional[str] = ""
    company: Optional[str] = ""
    phone: Optional[str] = ""
    mobile: Optional[str] = ""
    address: Optional[AddressInfo] = None
    website: Optional[str] = ""
    raw_text: Optional[str] = ""


class ScanRequest(BaseModel):
    image_data: str
    event_name: str


class ScanResponse(BaseModel):
    card: CardInfo
    event_name: str


class CompanyLookupRequest(BaseModel):
    company_name: str


class CompanyLookupResponse(BaseModel):
    company_name: str
    summary: str       # Gemini Grounding 回傳的公司簡介
    sources: list[str] = []  # grounding 來源 URL


class CollaborationHintRequest(BaseModel):
    company_name: str
    company_summary: str


class CollaborationHintResponse(BaseModel):
    hint: str          # GPT-5.5 生成的合作機會描述


class SendRequest(BaseModel):
    card: CardInfo
    event_name: str
    collaboration_hint: Optional[str] = ""  # 選填，空字串代表不嵌入


class SendResponse(BaseModel):
    success: bool
    message: str
    recipient_email: Optional[str] = ""


class UserSession(BaseModel):
    email: str
    name: str
    picture: Optional[str] = ""
    access_token: str
    refresh_token: Optional[str] = None
