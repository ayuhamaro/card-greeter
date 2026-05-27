import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from authlib.integrations.starlette_client import OAuth
from app.config import get_settings
from app.models import UserSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# OAuth 客戶端設定
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.send"  # 寄信權限
        ),
        "access_type": "offline",   # 取得 refresh_token
        "prompt": "consent",        # 強制顯示同意畫面（確保每次都拿到 refresh_token）
    },
)


@router.get("/login")
async def login(request: Request):
    """重導向至 Google OAuth2 同意畫面"""
    redirect_uri = f"{settings.app_base_url}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """
    Google OAuth2 callback
    - 驗證 token
    - 白名單檢查（只允許 ALLOWED_EMAIL）
    - 寫入 session
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(status_code=400, detail="OAuth authentication failed.")

    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(status_code=400, detail="Could not retrieve user info.")

    user_email = user_info.get("email", "")

    # ─── 白名單檢查 ──────────────────────────────────────────
    if user_email.lower() != settings.allowed_email.lower():
        logger.warning(f"Unauthorized login attempt: {user_email}")
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. This service is restricted to authorized users only.",
        )

    # 寫入 session（itsdangerous 加密，儲存在 cookie）
    request.session["user"] = {
        "email": user_email,
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
    }

    logger.info(f"User logged in: {user_email}")
    return RedirectResponse(url="/")


@router.get("/logout")
async def logout(request: Request):
    """清除 session"""
    request.session.clear()
    return RedirectResponse(url="/")


@router.get("/me")
async def me(request: Request):
    """回傳當前登入使用者資訊（前端用於判斷登入狀態）"""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"logged_in": False})
    return JSONResponse({
        "logged_in": True,
        "name": user["name"],
        "email": user["email"],
        "picture": user["picture"],
    })


# ─── Dependency：要求已登入 ──────────────────────────────────
def require_auth(request: Request) -> dict:
    """
    FastAPI dependency，在需要驗證的 endpoint 使用
    用法：user = Depends(require_auth)
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user
