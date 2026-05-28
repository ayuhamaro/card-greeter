import json
import logging
import httpx
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
    },
)


@router.get("/login")
async def login(request: Request):
    """重導向至 Google OAuth2 同意畫面"""
    redirect_uri = f"{settings.app_base_url}/auth/callback"
    return await oauth.google.authorize_redirect(
        request, redirect_uri,
        access_type="offline",
        prompt="consent",
    )


@router.get("/callback")
async def callback(request: Request):
    """
    Google OAuth2 callback

    Session schema（最小化原則）：
      user.email   → 明文，作為識別 key
      user.name    → 明文，供 /me 回傳前端顯示
      user.vault   → Fernet 加密的 {access_token, refresh_token}

    picture URL 不存入 session：
      - 長度 100~400 bytes，佔用寶貴的 Cookie 空間
      - 改由登入時一次性回傳給前端，前端用 JS 變數快取
      - 頁面重整後重新向 /me 取得（/me 會向 Google userinfo API 查詢）
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
    vault = _encrypt({
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
    })

    # picture 不進 session，存入獨立的短期 key，供前端首次載入時取得
    # 此 key 在 /me 被讀取後即刪除（one-shot），後續由前端 JS 變數維護
    request.session["user"] = {
        "email": user_email,
        "name": user_info.get("name", ""),
        "vault": vault,
    }
    request.session["_picture"] = user_info.get("picture", "")

    logger.info(f"User logged in: {user_email}")
    return RedirectResponse(url="/")


@router.get("/logout")
async def logout(request: Request):
    """撤銷 Google OAuth token 後清除 session"""
    user = request.session.get("user")
    if user:
        try:
            tokens = _decrypt(user["vault"])
            revoke_token = tokens.get("refresh_token") or tokens.get("access_token")
            if revoke_token:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": revoke_token},
                    )
        except Exception as e:
            logger.warning(f"Token revocation failed during logout: {e}")
    request.session.clear()
    return RedirectResponse(url="/")


@router.get("/me")
async def me(request: Request):
    """
    回傳當前登入使用者資訊（前端用於判斷登入狀態）

    picture 處理策略：
      - 登入後首次呼叫：從 session["_picture"] 取得並刪除（one-shot），
        前端收到後用 JS 變數快取，不再依賴 session
      - 後續呼叫（頁面重整等）：session["_picture"] 已不存在，
        回傳空字串，前端隱藏大頭貼或顯示預設圖示
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"logged_in": False})

    # one-shot 取得 picture，取完即從 session 移除
    picture = request.session.pop("_picture", "")

    return JSONResponse({
        "logged_in": True,
        "name": user["name"],
        "email": user["email"],
        "picture": picture,
    })


def update_vault(request: Request, new_access_token: str) -> None:
    """
    Token 刷新後，將新的 access_token 加密回寫至 session vault
    由 mail_router 在 Gmail SDK 自動刷新後呼叫
    """
    user = request.session.get("user")
    if not user:
        return
    try:
        current = _decrypt(user["vault"])
        current["access_token"] = new_access_token
        user["vault"] = _encrypt(current)
        request.session["user"] = user
        logger.info("Session vault updated with refreshed access_token.")
    except Exception as e:
        logger.warning(f"Failed to update vault after token refresh: {e}")


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
