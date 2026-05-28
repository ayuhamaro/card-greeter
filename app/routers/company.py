import logging
from fastapi import APIRouter, Depends, HTTPException
from app.models import (
    CompanyLookupRequest, CompanyLookupResponse,
    CollaborationHintRequest, CollaborationHintResponse,
)
from app.services.company_service import CompanyService
from app.services.collaboration_service import CollaborationService
from app.routers.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["company"])

company_service = CompanyService()
collaboration_service = CollaborationService()


@router.post("/company-lookup", response_model=CompanyLookupResponse)
async def company_lookup(
    payload: CompanyLookupRequest,
    user: dict = Depends(require_auth),
):
    """
    用 Gemini Grounding 查詢公司資料
    手動觸發，使用者可選擇不執行直接寄信
    """
    company_name = payload.company_name.strip()
    if not company_name:
        raise HTTPException(status_code=422, detail="Company name is required.")

    logger.info(f"[{user['email']}] Company lookup: {company_name}")

    try:
        result = await company_service.lookup(company_name)
    except Exception as e:
        logger.error(f"Gemini Grounding error: {e}")
        raise HTTPException(status_code=502, detail="Failed to look up company. Please try again.")

    return CompanyLookupResponse(
        company_name=company_name,
        summary=result["summary"],
        sources=result["sources"],
    )


@router.post("/collaboration-hint", response_model=CollaborationHintResponse)
async def collaboration_hint(
    payload: CollaborationHintRequest,
    user: dict = Depends(require_auth),
):
    """
    根據公司簡介生成合作機會描述
    由前端在 company-lookup 完成後自動觸發
    """
    if not payload.company_summary.strip():
        raise HTTPException(status_code=422, detail="Company summary is required.")

    logger.info(f"[{user['email']}] Generating collaboration hint: {payload.company_name}")

    try:
        hint = await collaboration_service.generate(
            company_name=payload.company_name,
            company_summary=payload.company_summary,
        )
    except Exception as e:
        logger.error(f"Collaboration hint generation error: {e}")
        raise HTTPException(status_code=502, detail="Failed to generate collaboration hint.")

    return CollaborationHintResponse(hint=hint)
