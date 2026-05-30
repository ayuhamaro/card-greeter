import logging
from typing import Optional
from fastapi import BackgroundTasks
from app.config import Settings
from app.models import CardInfo
from app.services.pubsub import PubSubService

logger = logging.getLogger(__name__)


def schedule_card_event(
    background_tasks: BackgroundTasks,
    pubsub: Optional[PubSubService],
    settings: Settings,
    sender_email: str,
    event_name: str,
    card: CardInfo,
) -> None:
    if pubsub is None:
        return
    if not card.name or not card.company:
        logger.info(
            f"[PubSub] Skipped: missing name or company "
            f"(name={card.name!r}, company={card.company!r})"
        )
        return
    background_tasks.add_task(
        pubsub.publish_card_event,
        sender_email=sender_email,
        sender_line_id=settings.sender_line_id,
        event_name=event_name,
        card=card,
        collaboration_hints=settings.collaboration_hints,
    )
