import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.config import get_settings
from app.models import CardInfo

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "template"


class TemplateService:
    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
        )
        self.settings = get_settings()

    def _build_context(
        self,
        card: CardInfo,
        event_name: str,
        collaboration_hint: str = "",
    ) -> dict:
        return {
            "sender_name": self.settings.sender_name,
            "sender_bio": self.settings.sender_bio,
            "event_name": event_name,
            "recipient_name": card.name,
            "recipient_title": card.title or "",
            "company_name": card.company or "貴公司",
            "collaboration_hint": collaboration_hint.strip(),
            "github_repo_url": self.settings.github_repo_url,
        }

    def render_subject(self, card: CardInfo, event_name: str) -> str:
        template = self.env.get_template("email_subject.txt")
        context = self._build_context(card, event_name)
        return template.render(**context).strip()

    def render_body(
        self,
        card: CardInfo,
        event_name: str,
        collaboration_hint: str = "",
    ) -> str:
        template = self.env.get_template("email_body.html.j2")
        context = self._build_context(card, event_name, collaboration_hint)
        return template.render(**context)
