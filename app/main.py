import logging
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app.config import get_settings
from app.routers import auth, card, mail, company

# ─── Logging 設定 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# ─── FastAPI App ───────────────────────────────────────────
app = FastAPI(
    title="Business Card Greeter",
    description="新創交流名片問候助理",
    version="1.0.0",
    docs_url="/docs" if settings.app_base_url.startswith("http://localhost") else None,
    redoc_url=None,
)

# ─── Global Exception Handler ─────────────────────────────
# 攔截所有非預期例外，確保 traceback 只寫進 log，不流出至 HTTP response
# 防止套件內部路徑、局部變數、加密字串片段等敏感資訊洩漏
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception: {type(exc).__name__} on "
        f"{request.method} {request.url.path}",
        exc_info=True,  # traceback 完整寫入 log，不進 response
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )

# ─── Proxy Headers Middleware ─────────────────────────────
# 讓 Starlette 正確讀取 Nginx 傳遞的 X-Forwarded-Proto
# 確保 https_only Session Cookie 在 SSL Termination 架構下正常運作
# trusted_hosts="127.0.0.1"：只信任來自本機 Nginx 的 proxy header
is_production = not settings.app_base_url.startswith("http://localhost")
if is_production:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")

# ─── Session Middleware (itsdangerous 加密 cookie) ─────────
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    max_age=60 * 60 * 8,    # 8 小時（一個活動的時長）
    https_only=is_production,
    same_site="lax",
)

# ─── Routers ──────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(card.router)
app.include_router(mail.router)
app.include_router(company.router)

# ─── Static files (SPA frontend) ──────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_spa():
    """SPA 入口，所有路由都回傳 index.html"""
    return FileResponse("static/index.html")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "business-card-greeter"}


logger.info("Business Card Greeter started.")
