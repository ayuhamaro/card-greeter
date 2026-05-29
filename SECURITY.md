這是一份針對「名片問候助理 (Business Card Greeter)」的程式碼與架構安全審查報告。本報告依據您提供的 FastAPI / 前端原始碼與系統組態，從應用層、基礎設施對齊以及 LLM 整合邊界等面向進行深入分析。

---

## 1. 優良安全實作

在進行風險盤點前，系統中已有數項值得肯定的安全設計，建議在後續重構中持續保留這些安全不變量（Invariants）：

* **全域例外攔截與錯誤去敏感化**
* **位置：** `app\main.py` 的 `global_exception_handler`
* **設計說明：** 攔截所有未處理例外，將 traceback 與詳細錯誤寫入 Server Log，而僅對 Client 回傳標準的 500 JSON。
* **安全價值：** 有效防止套件內部路徑、加密金鑰或局部變數等敏感資訊透過 HTTP Response 洩漏（Information Disclosure）。


* **最小化 Session 儲存與 Token 隔離加密**
* **位置：** `app\routers\auth.py` 的 `_encrypt` 與 Session 寫入邏輯
* **設計說明：** Session Cookie 僅明文存放不具敏感性的識別資訊（email, name），而將高權限的 OAuth Access / Refresh Token 透過 Fernet 加密後存入 `vault`。
* **安全價值：** 即使 Cookie 被盜取或外洩，攻擊者也無法直接取得明文的 Google API Token；同時配合 `max_age` 與 `same_site="lax"` 縮小了 CSRF 與 Session Hijacking 的攻擊面。


* **嚴格的認證白名單邊界**
* **位置：** `app\routers\auth.py` 的 `allowed_email` 檢查
* **設計說明：** 系統直接在 OAuth Callback 階段阻擋非白名單信箱。
* **安全價值：** 避免服務暴露於公網時遭任意使用者登入，進而濫用配額昂貴的 LLM API 服務。


* **強型別的 LLM 輸出驗證 (Structured Outputs)**
* **位置：** `app\services\vision_service.py` 的 `CardExtraction` 類別
* **設計說明：** 使用 Pydantic schema 與 OpenAI GPT-4o 的 `response_format`，強制模型回傳符合預期格式的 JSON。
* **安全價值：** 消除 LLM 輸出格式漂移（Format drift）的風險，並在一定程度上阻斷 Prompt Injection 導致模型吐出惡意指令的可能。


* **前端動態渲染防範 XSS**
* **位置：** `static\index.html` 的 `lookupCompany` 函式
* **設計說明：** 解析 Gemini 來源 URL 時，強制驗證 `http://` 或 `https://` 前綴，並使用 `document.createElement` 動態建構 DOM 節點，而非依賴 `innerHTML`。
* **安全價值：** 防止 LLM 回傳惡意的 `javascript:` 偽協議 URL 所導致的 DOM-based XSS 攻擊。



---

## 2. 核心安全風險與修復建議

### 風險項目：缺少 Request Body 與輸入欄位長度限制 (DoS / OOM 風險)

* **嚴重程度：** High
* **影響範圍：** 應用層 / 資源耗用
* **涉及位置：** `app\models.py` 的 `ScanRequest`、`main.py`
* **問題描述：** `ScanRequest` 接受 base64 格式的 `image_data` 字串，但未設定最大長度。攻擊者（或異常的前端行為）可以發送數百 MB 的超大 Payload。由於 FastAPI / Uvicorn 預設不嚴格限制 Body Size，這將導致記憶體耗盡（OOM）或嚴重拖垮事件迴圈（Event Loop）。
* **攻擊情境或失效條件：** 授權使用者帳號遭挾持，或惡意內部人員以腳本大量 POST 巨大的 Base64 字串至 `/api/scan`。
* **修復建議：** 於 Pydantic 模型中針對欄位增加長度約束（`max_length`），並於應用層或 Nginx 設定中加入 Payload Size 限制。

### 風險項目：反向代理信任主機 (Trusted Hosts) 與 Docker 網路設定落差

* **嚴重程度：** Medium
* **影響範圍：** 基礎設施 / Session
* **涉及位置：** `app\main.py` 的 `ProxyHeadersMiddleware`
* **問題描述：** 程式碼中硬編碼了 `trusted_hosts="127.0.0.1"`。若應用程式部署在 Docker 容器內，Nginx 通常透過 Docker Bridge Network (例如 `172.x.x.x`) 轉發流量，此時來源 IP 並非 `127.0.0.1`。
* **攻擊情境或失效條件：** `ProxyHeadersMiddleware` 會拒絕解析來自非 127.0.0.1 的 `X-Forwarded-Proto`，導致 FastAPI 以為請求是 HTTP。這將觸發 `SessionMiddleware` 中 `https_only=True` 的失效（Cookie 無法正確被寫入瀏覽器），或引發無窮的 HTTPS 重新導向迴圈。
* **修復建議：** 將 `trusted_hosts` 抽離至 `.env` 環境變數，使其能在容器環境中配置為實際的 Proxy IP（或 `*`，若網路邊界已在外部受到嚴格保護）。

### 風險項目：缺少 LLM API 速率限制 (Rate Limiting) 與成本消耗控制

* **嚴重程度：** Medium
* **影響範圍：** 資源耗用 / 外部整合
* **涉及位置：** `app\routers\card.py`、`app\routers\company.py`
* **問題描述：** 提供 GPT-4o Vision 與 Gemini Grounding 的 API 介面沒有任何防呆或 Rate Limit 限制。
* **攻擊情境或失效條件：** 即使有白名單保護，合法使用者可能因前端 Bug（如狂按按鈕）、腳本錯誤，在短時間內發送大量請求，導致 OpenAI / Google 帳單爆增，或觸發 API 供應商的 Rate Limit 導致服務中斷。
* **修復建議：** 引入 `slowapi` 等套件，基於使用者 Email 設定 Token bucket 的速率限制（例如：每分鐘最多 10 次名片掃描）。

### 風險項目：Pydantic V2 設定檔相容性隱患

* **嚴重程度：** Low
* **影響範圍：** 應用層設定
* **涉及位置：** `app\config.py`
* **問題描述：** 類別繼承自 `pydantic_settings.BaseSettings` (此為 Pydantic V2 寫法)，但內部設定檔載入卻使用 `class Config:` (此為 Pydantic V1 寫法)。
* **攻擊情境或失效條件：** 在某些版本的 Pydantic V2 中，`class Config` 會被靜默忽略，導致環境變數（如 `session_secret_key`）載入失敗或回退至預設值，可能引發未預期的啟動失敗或機敏資料處理異常。
* **修復建議：** 改用 Pydantic V2 官方建議的 `model_config = SettingsConfigDict(...)` 宣告方式。

---

## 3. 建議重構範例

### A. Pydantic 模型安全約束 (修復 OOM 風險)

在 `models.py` 中明確宣告字串長度，提早在反序列化階段擋下巨大 Payload：

```python
from pydantic import BaseModel, Field

class ScanRequest(BaseModel):
    # 限制 base64 圖片長度 (例如限制為 ~10MB 左右的 Base64 長度)
    image_data: str = Field(..., max_length=15_000_000)
    # 限制一般文字輸入，防範過長的惡意字串
    event_name: str = Field(..., max_length=100)

class CompanyLookupRequest(BaseModel):
    company_name: str = Field(..., max_length=100)

```

### B. 基礎架構 Proxy 設定對齊與 Pydantic V2 重構

更新 `config.py` 以支援動態 Proxy IP，並修正 Pydantic 寫法：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union

class Settings(BaseSettings):
    # ... 省略原有欄位 ...
    
    # 增加 proxy hosts 設定，允許逗號分隔或 *
    trusted_proxy_hosts: Union[str, List[str]] = "127.0.0.1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

```

並在 `main.py` 中套用：

```python
# 將逗號分隔字串轉為 list
trusted_hosts = settings.trusted_proxy_hosts
if isinstance(trusted_hosts, str):
    trusted_hosts = [h.strip() for h in trusted_hosts.split(",")]

if is_production:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)

```

---

## 4. 生產環境部署配置建議

若此服務透過 Nginx 作為反向代理並掛載 TLS，為了讓 FastAPI 的 SessionMiddleware 與 ProxyHeadersMiddleware 正常運作，並阻擋過大的惡意請求，請參考以下 `nginx.conf` 設定片段：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # 基礎 TLS 設定 (略)

    # 應用層安全 Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: https:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://accounts.google.com;";
    add_header Referrer-Policy strict-origin-when-cross-origin;

    # 嚴格限制客戶端上傳 Body Size (對齊 Pydantic 的 15MB 限制)
    client_max_body_size 15M;

    location / {
        proxy_pass http://127.0.0.1:8000; # 或指向 Docker container 的 hostname
        
        # 必須正確傳遞這些 Header，FastAPI 才能識別 HTTPS 與真實 IP
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 逾時設定，防止 LLM API 等待過久佔用連線
        proxy_read_timeout 60s;
        proxy_connect_timeout 15s;
    }
}

```

---

## 5. 優先修復清單

| 優先級 | 項目 | 風險 | 建議處理方式 |
| --- | --- | --- | --- |
| **P0** | **基礎設施 Proxy 參數設定** | 可能導致 Production 部署時 HTTPS Cookie 無法寫入，引發無限登入迴圈。 | 將 `trusted_hosts` 改為環境變數設定，對齊 Docker 網路架構。 |
| **P1** | **輸入邊界與長度限制** | `ScanRequest` 無長度限制，可能導致記憶體耗盡（OOM）引發服務中斷。 | 在 `models.py` 補上 Pydantic `Field(max_length=...)`，並設定 Nginx `client_max_body_size`。 |
| **P1** | **Pydantic Config 相容性** | 可能導致 `.env` 敏感機密變數載入失敗，破壞加密機制。 | 升級為 V2 寫法 `model_config = SettingsConfigDict(...)`。 |
| **P2** | **加入 API 速率限制** | LLM 資源被惡意或異常耗用，造成超額帳單。 | 導入 `slowapi`，基於登入的 User Email 實施 Rate Limiting。 |

---

## 6. 總結

本專案在身分認證、敏感錯誤去識別化以及 LLM 提示工程（Prompt Engineering / Structured Outputs）上，已具備相當成熟的防禦觀念，是一套設計良好的內部輔助工具。目前最需優先處理的是 **Nginx 與 FastAPI 之間的網路信任邊界（Proxy Headers）對齊**，以及**應用層對使用者輸入長度的約束**。完成 P0 與 P1 修復後，系統在面對極端輸入與部署環境變化時，將具備高度的可用性與穩定性。