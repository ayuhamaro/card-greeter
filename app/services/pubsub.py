import json
import logging
from datetime import datetime, timezone, timedelta
from google.cloud import pubsub_v1
from google.oauth2 import service_account
from app.models import CardInfo

logger = logging.getLogger(__name__)

_PUBSUB_SCOPES = ["https://www.googleapis.com/auth/pubsub"]
_TZ_TAIPEI = timezone(timedelta(hours=8))


def build_publisher(credentials_file: str) -> pubsub_v1.PublisherClient:
    credentials = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=_PUBSUB_SCOPES
    )
    return pubsub_v1.PublisherClient(credentials=credentials)


class PubSubService:
    def __init__(self, publisher: pubsub_v1.PublisherClient, topic_path: str):
        self._publisher = publisher
        self._topic_path = topic_path

    def publish_card_event(
        self,
        sender_email: str,
        sender_line_id: str,
        event_name: str,
        card: CardInfo,
        collaboration_hints: str,
    ) -> None:
        payload = {
            "sent_at": datetime.now(tz=_TZ_TAIPEI).isoformat(),
            "sender_email": sender_email,
            "sender_line_id": sender_line_id,
            "event_name": event_name,
            "card": card.model_dump(),
            "collaboration_hints": collaboration_hints,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        future = self._publisher.publish(self._topic_path, data)
        future.add_done_callback(_on_publish_done)


def _on_publish_done(future) -> None:
    try:
        message_id = future.result()
        logger.info(f"[PubSub] Published message_id={message_id}")
    except Exception as e:
        logger.error(f"[PubSub] Publish failed: {e}")
