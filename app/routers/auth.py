import json
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet, InvalidToken
from app.config import get_settings
from app.models import UserSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# ─── Fernet 加密器（模組載入時初始化一次）────────────────────
_fernet = Fernet(settings.session_encrypt_key.encode())


def _encrypt(data: dict) -> str:
    """將敏感 dict 加密為 Fernet token 字串"""
    return _fernet.encrypt(json.dumps(data).encode()).decode()


def _decrypt(token: str) -> dict:
    """解密 Fernet token 字串，回傳原始 dict"""
    return json.loads(_fernet.decrypt(token.encode()))


# ─── OAuth 客戶端 ─────────────────────────────────────────────
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.send"
        ),
        "access_type": "offline",
        "prompt": "consent",
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
    Session 結構：
      user.email / user.name  → 明文（非敏感，供前端 /me 使用）
      user.vault              → Fernet 加密的 {access_token, refresh_token}
    picture URL 刻意不存入 session（避免撐爆 4KB Cookie 限制）
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

    # ─── 白名單檢查 ───────────────────────────────────────────
    if user_email.lower() != settings.allowed_email.lower():
        logger.warning(f"Unauthorized login attempt: {user_email}")
        raise HTTPException(
            status_code=403,
            detail="Access denied. This service is restricted to authorized users only.",
        )

    # ─── Token 加密後存入 session ─────────────────────────────
    # vault：只存敏感 token，Fernet 加密
    # 非敏感的 email / name 明文存放，供 /me 直接讀取
    # picture URL 不存入 session（通常 200~400 bytes，省下寶貴 Cookie 空間）
    vault = _encrypt({
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
    })

    request.session["user"] = {
        "email": user_email,
        "name": user_info.get("name", ""),
        "vault": vault,
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
    })


# ─── Dependency：要求已登入，並解密 vault 回傳完整 user dict ──
def require_auth(request: Request) -> dict:
    """
    FastAPI dependency，在需要驗證的 endpoint 使用
    回傳值包含解密後的 access_token / refresh_token
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    try:
        tokens = _decrypt(user["vault"])
    except (InvalidToken, KeyError) as e:
        logger.warning(f"Failed to decrypt session vault: {e}")
        raise HTTPException(
            status_code=401,
            detail="Session token invalid or expired. Please re-login.",
        )

    return {
        "email": user["email"],
        "name": user["name"],
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
    }
