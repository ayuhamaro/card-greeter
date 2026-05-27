import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from app.models import SendRequest, SendResponse
from app.services.template_service import TemplateService
from app.services.gmail_service import GmailService
from app.routers.auth import require_auth
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mail"])

template_service = TemplateService()
gmail_service = GmailService()


@router.post("/send", response_model=SendResponse)
async def send_greeting(
    request: Request,
    payload: SendRequest,
    user: dict = Depends(require_auth),
):
    """
    用確認過的名片資訊渲染郵件樣板，並透過 Gmail API 寄出
    
    Flow: CardInfo + event_name
        → TemplateService.render_subject / render_body
        → GmailService.send_email (OAuth2 token from session)
    
    INVARIANT: 此 endpoint 不會重新掃描名片，只負責寄信
    """
    card = payload.card
    event_name = payload.event_name

    # 驗證收件人 email
    if not card.email or "@" not in card.email:
        raise HTTPException(
            status_code=422,
            detail="Recipient email is missing or invalid. Please edit it before sending.",
        )

    # 從 session 取得 Gmail token
    session_user = request.session.get("user", {})
    access_token = session_user.get("access_token")
    refresh_token = session_user.get("refresh_token")
    sender_email = session_user.get("email")

    if not access_token:
        raise HTTPException(status_code=401, detail="Gmail token not found. Please re-login.")

    logger.info(f"[{sender_email}] Sending greeting to {card.email} ({card.name})")

    # 渲染樣板
    try:
        subject = template_service.render_subject(card, event_name)
        html_body = template_service.render_body(card, event_name)
    except Exception as e:
        logger.error(f"Template rendering error: {e}")
        raise HTTPException(status_code=500, detail="Failed to render email template.")

    # 寄送
    try:
        await gmail_service.send_email(
            access_token=access_token,
            sender_email=sender_email,
            recipient_email=card.email,
            subject=subject,
            html_body=html_body,
            refresh_token=refresh_token,
        )
    except HttpError as e:
        status_code = e.resp.status if hasattr(e, "resp") else 500
        if status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Gmail token expired. Please logout and re-login.",
            )
        logger.error(f"Gmail API HttpError: {e}")
        raise HTTPException(status_code=502, detail="Failed to send email via Gmail.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return SendResponse(
        success=True,
        message=f"Email sent to {card.name} ({card.email})",
        recipient_email=card.email,
    )
