import logging
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from app.config import get_settings
from app.models import SendRequest, SendResponse
from app.services.template import TemplateService
from app.services.gmail import GmailService
from app.services.pubsub import PubSubService
from app.libs.card_event import schedule_card_event
from app.routers.auth import require_auth, update_vault
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mail"])

settings = get_settings()
template_service = TemplateService()
gmail_service = GmailService()


def get_pubsub(request: Request) -> Optional[PubSubService]:
    return request.app.state.pubsub


@router.post("/send", response_model=SendResponse)
async def send_greeting(
    request: Request,
    payload: SendRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth),
    pubsub: Optional[PubSubService] = Depends(get_pubsub),
):
    card = payload.card
    event_name = payload.event_name

    if not card.email or "@" not in card.email:
        raise HTTPException(
            status_code=422,
            detail="Recipient email is missing or invalid. Please edit it before sending.",
        )

    access_token = user["access_token"]
    refresh_token = user.get("refresh_token")
    sender_email = user["email"]

    logger.info(f"[{sender_email}] Sending greeting to {card.email} ({card.name})")

    try:
        subject = template_service.render_subject(card, event_name)
        html_body = template_service.render_body(
            card, event_name,
            collaboration_hint=payload.collaboration_hint or "",
        )
    except Exception as e:
        logger.error(f"Template rendering error: {e}")
        raise HTTPException(status_code=500, detail="Failed to render email template.")

    try:
        _, current_token = await gmail_service.send_email(
            access_token=access_token,
            sender_email=sender_email,
            recipient_email=card.email,
            subject=subject,
            html_body=html_body,
            refresh_token=refresh_token,
        )
    except HttpError as e:
        http_status = e.resp.status if hasattr(e, "resp") else 500
        # 精準提取 status code 與 error_details，避免 dump 整個 exception
        # 防止 Raw HTTP response 中的敏感上下文寫入日誌
        error_detail = e.error_details if hasattr(e, "error_details") else "no detail"
        if http_status == 401:
            raise HTTPException(
                status_code=401,
                detail="Gmail token expired. Please logout and re-login.",
            )
        logger.error(f"Gmail API failed. status={http_status}, detail={error_detail}")
        raise HTTPException(status_code=502, detail="Failed to send email via Gmail.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ─── Token 刷新回寫 ───────────────────────────────────────
    # SDK 自動刷新後 current_token 會與原始 access_token 不同
    # 回寫確保下一次請求不會用到過期的 token
    if current_token and current_token != access_token:
        update_vault(request, current_token)

    # ─── Pub/Sub 事件發布（背景執行，不阻塞回應）────────────────
    schedule_card_event(background_tasks, pubsub, settings, sender_email, event_name, card)

    return SendResponse(
        success=True,
        message=f"Email sent to {card.name} ({card.email})",
        recipient_email=card.email,
    )
