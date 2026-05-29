import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from app.models import SaveContactRequest, SaveContactResponse
from app.services.contacts_service import ContactsService
from app.routers.auth import require_auth, update_vault
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["contacts"])

contacts_service = ContactsService()


@router.post("/save-contact", response_model=SaveContactResponse)
async def save_contact(
    request: Request,
    payload: SaveContactRequest,
    user: dict = Depends(require_auth),
):
    """
    呼叫 Google People API 將名片資料建立為新聯絡人
    token 若在過程中被刷新，回寫 session vault
    """
    access_token = user["access_token"]
    refresh_token = user.get("refresh_token")

    logger.info(
        f"[{user['email']}] Saving contact: {payload.first_name} {payload.last_name}"
    )

    try:
        result, current_token = await contacts_service.save_contact(
            access_token=access_token,
            refresh_token=refresh_token,
            req=payload,
        )
    except HttpError as e:
        http_status = e.resp.status if hasattr(e, "resp") else 500
        error_detail = e.error_details if hasattr(e, "error_details") else "no detail"
        if http_status == 401:
            raise HTTPException(
                status_code=401,
                detail="Google token expired. Please logout and re-login.",
            )
        if http_status == 403:
            raise HTTPException(
                status_code=403,
                detail="Missing contacts permission. Please logout and re-login to grant access.",
            )
        logger.error(f"People API failed. status={http_status}, detail={error_detail}")
        raise HTTPException(status_code=502, detail="Failed to save contact. Please try again.")
    except Exception as e:
        logger.error(f"Contacts save error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save contact.")

    if current_token and current_token != access_token:
        update_vault(request, current_token)

    display_name = (
        f"{payload.first_name} {payload.last_name}".strip()
        or payload.email
        or "Unknown"
    )
    return SaveContactResponse(
        success=True,
        contact_name=display_name,
        resource_name=result.get("resourceName", ""),
    )
