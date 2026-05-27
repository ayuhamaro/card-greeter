# Code Security Assessment Report: Project `card-greeter`

本報告針對 `card-greeter` 專案的核心代碼進行安全審查（Code Review），重點評估配置值洩漏風險、狀態管理（Session）安全性，以及與反向代理（Nginx）搭配部署時潛在的架構缺陷。

---

## ─── 執行摘要 (Executive Summary) ───

整體而言，該專案在安全意識上有相當高水準的實作，例如採用了 **OpenAI Structured Outputs** 來收斂 Prompt Injection 的對域空間（Vector Space），並在客戶端 Cookie 簽章機制之外額外疊加了 **Fernet 對稱加密加密封套（Cryptographic Envelope）**。

然而，系統在**網路拓撲邊界（Reverse Proxy Boundary）**與**記憶體狀態邊界**上仍存在兩項重大的隱患，可能導致生產環境部署時 Session 失效或引發記憶體耗盡（DoS）攻擊。

---

## ─── 重大資安風險與架構漏洞分析 ───

### 1. Nginx 網路代理對齊陷阱：`ProxyHeadersMiddleware` 的主機信任硬編碼

* **定位檔案**：`app/main.py`
* **風險層級**：高 (High) — 導致生產環境部署失敗或安全機制降級
* **機制分析**：
代碼中配置了 `ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")`。如果該服務與 Nginx 部署在同一個物理主機上，且 Nginx 透過 `127.0.0.1:8000` 轉發，此設定安全無虞。
**但是，如果此專案未來使用 Docker 容器化部署**（例如透過 Docker Compose 將 Nginx 與 FastAPI 切分為不同服務），Nginx 轉發給 FastAPI 的 Ingress 流量將來自 Docker 內部網橋的閘道器 IP（如 `172.18.0.x`）。
* **連帶崩潰效應**：
當來源 IP 不匹配 `"127.0.0.1"` 時，`ProxyHeadersMiddleware` 會直接**忽略** Nginx 帶過來的 `X-Forwarded-Proto: https` 標頭。這會使 Starlette 誤判當前請求為不安全的 `http`。
隨後，`SessionMiddleware(https_only=True)` 將拒絕向瀏覽器寫入或讀取 Session Cookie，導致 OAuth 回呼（Callback）徹底失效，甚至引發 Authlib 產生 `Missing Redirect URI Mismatch` 或是重定向無窮迴圈。

```python
# 存在隱患的區塊
if is_production:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1") 
    # 若在 Docker 拓撲下，127.0.0.1 將無法正確匹配代理節點

```

### 2. 未限制大小的 Base64 圖片反序列化 (Memory Inflation DoS Vector)

* **定位檔案**：`app/routers/card.py` & `app/services/vision_service.py`
* **風險層級**：中高 (Medium-High)
* **機制分析**：
`/api/scan` 接收一個 `ScanRequest` 模型，其中的 `image_data` 是一個未限制長度的明文字串（Base64 Data URL）。 FastAPI/Uvicorn 默認會將整個 JSON Payload 載入記憶體中。
若惡意攻擊者繞過前端，直接對該端點併發發送內含 50MB~100MB 隨機字串的偽造請求，會導致伺服器記憶體空間（Memory Space）瞬間產生極高熵值的膨脹（Entropy Spike），極易觸發 Linux 核心的 OOM Killer，造成服務非預期終止。

---

## ─── 值得肯定的安全優良設計 (Security Highlights) ───

在審查過程中，我們也發現了幾處具備高度防禦性程式設計（Defensive Programming）思維的實作：

* **密鑰隔離防護 (`hide_input_in_errors = True`)**：在 `app/config.py` 的 Pydantic 配置中開啟此開關，有效防止當環境變數型態錯誤時，Traceback 將 API Key 噴出到日誌（Logger）中。
* **雙重安全 Session 結構**：開發者意識到 Starlette 的 `SessionMiddleware` 默認僅進行簽章（Signed）而非加密（Encrypted）。因此，代碼在寫入 `vault` 前使用 `Fernet` 對 Google OAuth Tokens 進行了對稱式加密。即使客戶端 Cookie 被惡意解碼，攻擊者也無法直接取得明文 Token。
* **結構化輸出防禦 (Schema Enforcement)**：在 `VisionService` 中使用 `client.beta.chat.completions.parse(response_format=CardExtraction)`，藉由 OpenAI 官方的強型態 Schema 限制模型輸出，這能近乎完美地免疫高風險的「提示詞注入攻擊（Prompt Injection）」，防止模型傳回惡意的控制字元。

---

## ─── 漏洞修復與優化建議清單 ───

### 修正建議 1：提升代理主機配置的彈性（動態 CIDR 或環境變數化）

為了讓系統能兼顧本機部署與 Docker 容器化拓撲，建議將 `trusted_hosts` 抽離至 `.env` 或預設支援網段。修改 `app/config.py` 增加 `trusted_proxies` 欄位：

```python
# app/config.py
class Settings(BaseSettings):
    # ... 其他設定
    trusted_proxies: str = "127.0.0.1" # 支援以逗號分隔或設定為 "*" 代表信任所有反向代理

```

並在 `app/main.py` 中進行解耦改寫：

```python
# app/main.py
if is_production:
    proxies = [p.strip() for p in settings.trusted_proxies.split(",")]
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=proxies)

```

### 修正建議 2：配合 Nginx 設定邊界防禦（Ingress Rate & Size Limiting）

雖然可以在 FastAPI 內部透過 Middleware 限制 Payload 大小，但最直覺且有效率（不佔用 Python 進程記憶體）的做法是在 Nginx 配置（或是 Docker 內部的 Nginx 節點）中直接設定 `client_max_body_size`：

```nginx
# nginx.conf
server {
    listen 443 ssl;
    server_name yourdomain.com;

    # 嚴格限制上傳的名片圖片大小上限為 10MB
    client_max_body_size 10M; 

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

```

### 修正建議 3：防範客戶端 Cookie 重放攻擊（Session Replay）

由於目前的 Session 完全依賴客戶端 Cookie（無狀態架構），`/auth/logout` 呼叫 `request.session.clear()` 僅能藉由 Response 清除瀏覽器端的 Cookie。若該 Cookie 在有效期限（8 小時）內被第三方側錄，即使使用者點擊了登出，該側錄的 Cookie 依然具有完整的存取權限。

* **短期緩解方案**：維持目前的 8 小時 `max_age`，這已將風險窗口（Vulnerability Window）限縮在單次活動範圍。
* **長期演進架構**：若未來有擴展多用戶之需求，建議將 Session 狀態儲存移至後端 KV 資料庫（如 Redis），將 Cookie 僅作為 Session ID 索引，達成真正的伺服器端狀態撤銷（Server-side Revocation）。