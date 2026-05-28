## 📇 Business Card Greeter 原始碼安全審查報告

這份報告針對 `card-greeter` 專案的核心架構、認證機制、LLM 整合以及與 Nginx 協同運作時的潛在資安風險進行深度審查。

整體而言，這份程式碼的資安意識**極高**。你處理敏感資訊的細緻度（例如在 Session Cookie 中引入 Fernet 二次加密、實作 One-shot 讀取大頭貼以優化 Cookie 空間、全域例外攔截防止 Traceback 外洩，以及前端精準的 XSS 防禦）顯著優於一般的開發標準。

然而，在預期將其部署於 Nginx 後端的情況下，仍有幾處隱藏的架構性風險（Architectural Risks）與邊界條件需要修正，以確保整體系統的低熵（Low Entropy）與高安全性。

---

## ── 優良安全實作亮點（High-Light）

在切入風險之前，這幾處設計非常漂亮，值得作為生產環境的 Schema 典範：

* **全域例外隔離（Global Exception Isolation）：** `main.py` 中的 `global_exception_handler` 完美切斷了內部錯誤流向 HTTP Response 的路徑。Traceback 完整寫入日誌，外在只看得到模糊的 `Internal server error.`，阻斷了攻擊者透過錯誤訊息進行路徑探測或環境變數搜集的可能性。
* **Session Vault 二次加密：** 由於 Starlette 的 `SessionMiddleware` 預設僅對 Cookie 進行簽章（Signing）而非加密（Encryption），敏感的 `access_token` 若明文存放，會暴露於客戶端瀏覽器。你引入 `Fernet` 進行對稱加密後再寫入 Cookie，完全解決了 Token 隱私外洩的問題。
* **防範流氓資料來源之 XSS 注入：** 在 `index.html` 的 `lookupCompany` 中，雖然 Gemini Grounding 的來源網址屬於外部不可控資料，但你使用了 `textContent` 配合嚴格的 `http://` / `https://` 協議開頭檢查，徹底封殺了透過 `javascript:` 偽協議進行 XSS 攻擊的威脅。
* **LLM 結構化輸出與間接 Prompt Injection 防禦：** `VisionService` 採用了 OpenAI 的 Structured Outputs (`response_format=CardExtraction`)，這在根本上強迫模型必須對齊 Pydantic 結構，杜絕了因名片內容包含惡意指令而導致 JSON 解析崩潰的風險。

---

## ── 核心資安風險與改進建議

### 1. Nginx 代理權限與 `trusted_hosts` 容器化斷層

* **程式碼片段：** `main.py`
```python
if is_production:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")

```


* **潛在問題：**
若你未來的部署策略是將 Nginx 與 FastAPI 分別包裝在不同的 Docker 容器中（並透過 Docker Compose Bridge 網路連結），Nginx 對於 FastAPI 而言其來源 IP **絕對不會是 `127.0.0.1**`，而是網域內的虛擬 IP（例如 `172.18.0.x`）。
一旦來源 IP 不在 `trusted_hosts` 白名單內，`ProxyHeadersMiddleware` 將會**拒絕解析** Nginx 傳遞的 `X-Forwarded-Proto` 等 Header。這會導致 FastAPI 誤以為當前請求仍是 HTTP，進而讓 `SessionMiddleware(https_only=True)` 在生產環境中**拒絕寫入或讀取 Cookie**，造成使用者無限登出。
* **修復方案：**
建議將 `trusted_hosts` 改為可透過環境變數配置，或在嚴格限定內部網路的 Docker 環境下改用 `["*"]`（但由 Nginx 負責把關外網存取）。
```python
# app/config.py 新增 proxy_trusted_hosts 配置
# main.py 修改為：
if is_production:
    trusted_hosts = [ip.strip() for ip in settings.proxy_trusted_hosts.split(",")]
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)

```



### 2. 客戶端 Cookie 體積膨脹與加密開銷（Cookie Overflow）

* **潛在問題：**
瀏覽器對單一網域的 Cookie 限制通常為 **4KB**。
在 `auth.py` 中，你的 `vault` 內含 Google 的 `access_token` 與 `refresh_token`。Google 的 Token 長度有時會因權限範圍與內部規格調整而增大（特別是帶有 Offline 權限的 Refresh Token）。
更重要的是，**Fernet (AES-128-CBC + HMAC) 加密會帶來顯著的體積膨脹**（約為原始明文的 1.3 到 2 倍，且會以 Base64 呈現）。雖然你已經極具遠見地將 `_picture` 自 Session 中 pop 掉，但若未來 Google Token 變長，仍有觸發 Cookie 超出 4KB 的臨界風險，導致瀏覽器無預警丟棄 Cookie。
* **修復方案：**
目前專案規模尚可安全運作。但若未來系統需要擴充功能或儲存更多狀態，建議將 `SessionMiddleware` 替換為**伺服器端 Session**（如將 Token 雜湊後存入伺服器記憶體/ Redis，Cookie 只留一個隨機的 `session_id`）。

### 3. 未限制的 Base64 圖片上傳體積（潛在的記憶體 DoS 攻擊）

* **程式碼片段：** `app/models.py` -> `ScanRequest(image_data: str)`
* **潛在問題：**
FastAPI 端直接接收了 `image_data: str` 的 Base64 字串，而 Pydantic 結構中並未限制該字串的長度上限。如果惡意攻擊者繞過前端，直接對 `/api/scan` 發送數百 MB 的巨大 Base64 字串，FastAPI 在解算 JSON 以及 `VisionService` 在執行 `base64.b64decode` 時，會瞬間榨乾伺服器記憶體，觸發 OOM (Out of Memory) 導致服務崩潰。
* **修復方案：**
此風險必須在 **Nginx 層面**進行硬性攔截（參見下一節的 Nginx 配置），同時也可以在 Pydantic Model 上施加長度約束：
```python
from pydantic import Field

class ScanRequest(BaseModel):
    # 限制 Base64 字串最大不超過 10MB (約等同 7MB 圖片)
    image_data: str = Field(..., max_length=10 * 1024 * 1024)
    event_name: str

```



---

## ── 生產環境 Nginx 配置規範範本

為了確保與 `card-greeter` 的 `ProxyHeadersMiddleware` 以及 `https_only=True` 安全隔離機制完美對齊，你的 Nginx 設定檔（`nginx.conf`）必須嚴格遵守以下範本配置：

```nginx
# 限制全域上傳體積，直接在傳輸層阻斷大圖 DoS 攻擊
client_max_body_size 10M;

server {
    listen 443 ssl http2;
    server_name card-greeter.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/card-greeter.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/card-greeter.yourdomain.com/privkey.pem;
    
    # 現代安全密碼組與協定
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 安全 Headers 防禦
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:;" always;

    location / {
        # 轉發至 FastAPI 容器或本機埠口
        proxy_pass http://127.0.0.1:8000; 
        
        # 核心：傳遞真實代理資訊，讓 ProxyHeadersMiddleware 能夠識別
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # 關鍵：告訴 FastAPI 當前用戶使用的是 HTTPS協定，確保 Secure Cookie 成功寫入
        proxy_set_header X-Forwarded-Proto $scheme;

        # 停用 Buffer 確保串流與即時連線流暢度（選用）
        proxy_buffering off;
        proxy_read_timeout 90s;
    }
}

```

---

## ── 總結

這份代碼展現了極其優異的防禦性編程（Defensive Programming）思維，在應用層已經把大部分 LLM 相關的注入與敏感資料外洩風險踩死。

**最終清單檢查：**

1. 確保部署時，Nginx 傳遞了 `X-Forwarded-Proto $scheme`。
2. 確保 FastAPI 的 `trusted_hosts` 能涵蓋 Nginx 的實際容器內網 IP。
3. 限制上傳的 Base64 體積。

完成上述微調後，這套架構將擁有極高的強韌度與低熵表現。