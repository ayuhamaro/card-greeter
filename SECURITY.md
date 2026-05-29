這是一份針對 `card-greeter`（新創交流名片問候助理）專案源碼的深度安全與架構審查報告。整體而言，本專案的防禦性編程（Defensive Programming）意識極高，在資料隱私、提示詞注入防禦以及錯誤阻斷上展現了非常成熟的設計。

以下從高維認知與架儲優化的視角，進行全方位的解構與赋能：

---

## ── 優良安全實作亮點 (High-Light)

本專案在多處核心邏輯中展現了極具遠見的防禦設計，有效降低了系統的熵值（Entropy）與攻擊面：

* **密鑰拉鍊保險箱（Token Vault Encryption）：** 在 `app\routers\auth.py` 中，系統並未將未加密的 Google OAuth2 `access_token` 與 `refresh_token` 直接寫入客戶端 Cookie Session，而是透過 `cryptography.fernet` 進行對稱加密後打包為 `vault` 存入。此舉大幅提升了資料在傳輸與存儲邊界時的抗竊聽與抗篡改強度。
* **動態邊界優化（Cookie Bloat Prevention）：** 針對 `picture` 這種非定長且佔用空間的頭像網址，採用 `one-shot`（一次性讀取即自 Session 彈出）並交由前端 JS 變數維護的設計。這完美迴避了 Starlette 客戶端 Cookie 超過 **4KB** 限制而導致 Session 隨機失效的架構性隱患。
* **LLM 整合層的雙重硬化防禦（Dual-Layer LLM Shielding）：** * 在 `VisionService` 中，利用 OpenAI 的 **Structured Outputs** (`response_format=CardExtraction`) 強制大型模型對齊 Pydantic Schema，從根本上免疫了名片內容可能夾帶的格式漂移（Format Drifting）與間接提示詞注入。
* 在 `CompanyService` 中，精心設計 Prompt 排除新聞、爭議事件，限縮 Gemini Grounding 的語意向量空間，有效切斷外部不可控網頁內容引發的間接注入威脅。


* **嚴格的例外資訊外洩阻斷（Information Leakage Isolation）：** `app\main.py` 實作了全域例外攔截器 `global_exception_handler`，確保所有非預期的 Traceback、內部路徑及依賴庫敏感細節只會留存在伺服器日誌（Logs）中，回傳給 HTTP Response 的僅有標準的群組化 JSON 訊息，避免技術債暴露給外部威脅源。

---

## ── 核心資安風險與改進建議

儘管基礎防線穩固，但在邊界條件對齊與資源調度上，仍存在以下三個架構性斷层風險：

### 1. 容器化網路拓撲下的代理對齊失效（Proxy Headers Mismatch）

* **程式碼片段 / 涉及模組：** `app\main.py`
```python
is_production = not settings.app_base_url.startswith("http://localhost")
if is_production:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")

```


* **潛在問題與架構風險：** 當此應用部署於現代容器化環境（如 Docker / Kubernetes）中，通常會以 Nginx 作為前端反向代理（Reverse Proxy）。在 Docker Bridge 網路架構下，Nginx 轉發請求給 FastAPI 時的來源 IP 通常是私有網段（如 `172.18.0.x`），而非 `127.0.0.1`。
這會導致 `ProxyHeadersMiddleware` 拒絕信任 Nginx 傳遞的 `X-Forwarded-Proto` 等標頭。進而引發內部 Schema 計算錯誤，使得 OAuth 回呼網址不一致，或是迫使 `SessionMiddleware` 的 `https_only=True` 因為無法識別 HTTPS 終端（SSL Termination）而拒絕寫入 Cookie。
* **修復方案 (Refactoring Solution)：**
應將信任的代理主機調整為支援環境變數配置，允許輸入子網段或動態讀取。
```python
# app\config.py 增加設定項目
class Settings(BaseSettings):
    # ...
    trusted_proxies: str = "127.0.0.1" # 支援以逗號分隔，例如 "127.0.0.1,172.16.0.0/12"

# app\main.py 修改
if is_production:
    proxies = [ip.strip() for ip in settings.trusted_proxies.split(",")]
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=proxies)

```



### 2. 未限制大小的 Base64 記憶體吞噬（Unbounded Payload DoS）

* **程式碼片段 / 涉及模組：** `app\models.py` -> `ScanRequest`
```python
class ScanRequest(BaseModel):
    image_data: str
    event_name: str

```


* **潛在問題與架構風險：** `image_data` 直接定義為不限長度的 `str`。當前端將手機拍攝的高解析度照片直接轉為 Base64 格式上傳時，惡意攻擊者可以發送高達 **50MB** 或更大的字串。
Pydantic 在對 JSON 進行反序列化時會將其全數加載至記憶體中。在高併發場景下，這種缺乏輸入邊界約束的設計會迅速耗盡伺服器記憶體，觸發 Linux 核心的 OOM Killer，導致服務非預期終止（Denial of Service, DoS）。
* **修復方案 (Refactoring Solution)：**
利用 Pydantic 的 `Field` 限制字串長度的上限值（例如限制 Base64 字串最大不超過 **15MB**，這已足夠容納一般高畫質名片截圖）。
```python
from pydantic import BaseModel, Field

class ScanRequest(BaseModel):
    # 15 * 1024 * 1024 限制字元長度
    image_data: str = Field(..., max_length=15728640, description="Base64 encoded card image")
    event_name: str = Field(..., max_length=100)

```



### 3. 客戶端 Cookie 體積爆破隱患（Client-Side Session Overflow）

* **程式碼片段 / 涉及模組：** `app\routers\auth.py` -> `callback()`
```python
vault = _encrypt({
    "access_token": token.get("access_token", ""),
    "refresh_token": token.get("refresh_token", ""),
})
request.session["user"] = { ... "vault": vault }

```


* **潛在問題與架構風險：** Starlette 的 `SessionMiddleware` 屬於純客戶端（Client-side）Cookie 機制。雖然 `Fernet` 提供了優異的加密保護，但密文（Ciphertext）的長度會比原文大幅膨脹（包含 IV、Timestamp 與 HMAC 簽章，具有高熵值且無法被二次壓縮）。
Google OAuth2 的 `access_token` 長度往往不固定，若加上 `refresh_token`，加密後的 `vault` 字串可能直逼 **2KB**。一旦加上 Session 的其他明文字段，總體 Cookie 長度極易突破瀏覽器 **4KB** 的臨界值。這會導致瀏覽器默默丟棄該 Cookie，使用者在下一次請求時會直接遭遇 401 未授權錯誤，造成難以排查的隨機登出現象。
* **修復方案 (Refactoring Solution)：**
雖然目前專案已透過 pop 排除 `_picture` 進行了優化，但若長期發展，強烈建議引入後端存儲型（Server-side）Session（如 Redis 或輕量化資料庫），Cookie 僅保留隨機的 `Session ID`。
*權宜修復方案：在寫入 Session 前對體積進行防禦性斷言（Assertion）檢驗：*
```python
import json
# 在寫入變數 request.session["user"] 後加入檢查
session_data_len = len(json.dumps(request.session.get("user", {})))
if session_data_len > 3000: # 預留 1KB 給其餘 Cookie 標頭與邊界
    logger.error(f"Session size risk: {session_data_len} bytes. OAuth tokens are too large.")
    raise HTTPException(status_code=500, detail="Authentication identity too large to store.")

```



---

## ── 生產環境配套配置規範範本 (Deployment Config)

為了補足「架構師的宏觀視野」，將代碼中的防禦邏輯與基礎設施對齊，本專案在生產環境布署時，必須為前端反向代理調校專屬的 `nginx.conf`。此配置能有效在網關邊界擋下 DoS 攻擊、防範 XSS 以及點擊劫持（Clickjacking）：

```nginx
# nginx.conf 安全硬化配置範本

# 限制客戶端上傳檔案（Base64 圖片）的最大容量，與應用層 Pydantic 邊界呼應
client_max_body_size 20M;

server {
    listen 443 ssl http2;
    server_name card-greeter.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/card-greeter.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/card-greeter.yourdomain.com/privkey.pem;
    
    # 現代安全密碼套件配置 (TLS 1.2 / TLS 1.3 Only)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;

    # ── 現代化防禦性安全標頭 (Security Headers) ──
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' https://fonts.googleapis.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self';" always;

    location / {
        proxy_pass http://127.0.0.1:8000; # 容器內部橋接網址
        
        # ── 核心 Proxy Headers 轉發（對齊 FastAPI ProxyHeadersMiddleware） ──
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # 確保 SSL Termination 架構下，FastAPI 能藉此識別並啟用 https_only Cookie
        proxy_set_header X-Forwarded-Proto $scheme;

        # 緩衝限制優化，防止大流量 JSON 上傳時頻繁寫入臨時磁碟導致效能斷崖
        proxy_buffering off;
        proxy_read_timeout 90s;
    }

    # 針對靜態資源優化快取管理，降低應用層負荷
    location /static/ {
        alias /app/static/;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }
}

```

---

## ── 總結

`Business Card Greeter` 在高難度的「多模態 LLM 擷取」與「OAuth 整合儲存」場景中，交出了一份安全意識極佳的答卷。其透過強韌的結構化輸出與加密沙盒機制，成功將最難預測的 AI 語意威脅和 Session 洩漏風險降至最低。後續只需將網路邊界的代理對齊（Proxy alignment）和內存防禦閥門（Payload limits）依照報告進行硬化調整，即可完美具備企業級的健壯度與生產環境應變能力。