import logging
from fastapi import APIRouter, Depends, HTTPException
from app.models import ScanRequest, ScanResponse
from app.services.vision import VisionService
from app.routers.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["card"])

# 服務實例（Singleton pattern in module scope）
vision_service = VisionService()


@router.post("/scan", response_model=ScanResponse)
async def scan_card(
    payload: ScanRequest,
    user: dict = Depends(require_auth),
):
    """
    接收前端上傳的名片圖片（base64），呼叫 GPT-4o Vision 擷取名片資訊
    
    Flow: base64 image → VisionService → CardInfo JSON
    回傳結果供前端顯示確認，使用者確認後再呼叫 /api/send
    """
    if not payload.image_data:
        raise HTTPException(status_code=400, detail="Image data is required.")
    if not payload.event_name.strip():
        raise HTTPException(status_code=400, detail="Event name is required.")

    logger.info(f"[{user['email']}] Scanning card for event: {payload.event_name}")

    try:
        card_info = await vision_service.extract_card_info(payload.image_data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Vision API error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process image. Please try again.")

    return ScanResponse(card=card_info, event_name=payload.event_name)
