import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.config import get_settings
from app.models import CardInfo

logger = logging.getLogger(__name__)

# 樣板目錄相對於專案根目錄
TEMPLATE_DIR = Path(__file__).parent.parent.parent / "template"


class TemplateService:
    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "j2"]),  # XSS 防護
        )
        self.settings = get_settings()

    def _build_context(self, card: CardInfo, event_name: str) -> dict:
        """組裝樣板變數，集中管理所有 placeholder 對應"""
        return {
            "sender_name": self.settings.sender_name,
            "sender_bio": self.settings.sender_bio,
            "event_name": event_name,
            "recipient_name": card.name,
            "recipient_title": card.title or "",
            "company_name": card.company or "貴公司",
        }

    def render_subject(self, card: CardInfo, event_name: str) -> str:
        """
        渲染郵件主旨
        樣板檔：template/email_subject.txt
        """
        template = self.env.get_template("email_subject.txt")
        context = self._build_context(card, event_name)
        return template.render(**context).strip()

    def render_body(self, card: CardInfo, event_name: str) -> str:
        """
        渲染 HTML 郵件內容
        樣板檔：template/email_body.html.j2
        """
        template = self.env.get_template("email_body.html.j2")
        context = self._build_context(card, event_name)
        return template.render(**context)
