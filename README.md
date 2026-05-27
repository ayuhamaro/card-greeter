# 名片問候助理 · Business Card Greeter

新創交流活動的一鍵問候工具：拍名片 → AI 識別 → Gmail 寄信

---

## 架構概覽

```
FastAPI Backend
├── /auth/*          Google OAuth2 登入 / 白名單驗證 / session
├── /api/scan        GPT-4o Vision 名片 OCR（Structured Outputs）
└── /api/send        Jinja2 渲染樣板 + Gmail API 寄信

Frontend (SPA)
└── static/index.html   手機相機拍攝 + 4步驟流程 UI

Session 安全設計
├── OAuth2 token     Fernet 對稱加密後存入 cookie（vault）
├── picture URL      不存入 session，改由前端 sessionStorage 快取
├── token 刷新       Gmail SDK 自動刷新後回寫 vault，無需重登
└── SSL Termination  ProxyHeadersMiddleware 確保 Nginx 後方的 https 上下文正確傳遞
```

---

## 快速設定

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定 Google Cloud Console

1. 前往 https://console.cloud.google.com
2. 建立新專案（或選擇現有專案）
3. 啟用 API（APIs & Services → Library）：
   - **Gmail API**
   - **Google People API**
4. 設定 OAuth 同意畫面（APIs & Services → OAuth consent screen）：
   - User Type：**External**
   - Scopes 加入：`userinfo.email`、`userinfo.profile`、`openid`、`gmail.send`
   - Test users 加入你自己的 Gmail（Testing 狀態下必填）
5. 建立 OAuth 2.0 憑證（Credentials → Create Credentials → OAuth 2.0 Client ID）：
   - 類型：**Web application**
   - Authorized redirect URIs 加入：`http://localhost:8000/auth/callback`
6. 複製 Client ID 與 Client Secret，填入 `.env`

### 3. 設定 `.env`

```bash
cp .env .env.example  # .env 為範本，複製後填入真實值
```

填入以下欄位（參考 `.env` 內的註解）：

| 欄位 | 說明 | 生成指令 |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API 金鑰 | — |
| `GOOGLE_CLIENT_ID` | GCP OAuth2 Client ID | — |
| `GOOGLE_CLIENT_SECRET` | GCP OAuth2 Client Secret | — |
| `SESSION_SECRET_KEY` | Session 簽章金鑰 | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_ENCRYPT_KEY` | Session Token 加密金鑰（Fernet） | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SENDER_NAME` | 寄件人姓名 | — |
| `SENDER_BIO_FILE` | 自我介紹 HTML 檔案的絕對路徑 | — |
| `ALLOWED_EMAIL` | 唯一允許登入的 Gmail | — |
| `APP_BASE_URL` | 本機開發用 `http://localhost:8000` | — |

### 4. 建立自我介紹檔案

自我介紹以 HTML 格式獨立存放，不進入 repo：

```bash
mkdir -p /path/to/config
vim /path/to/config/sender_bio.html
```

檔案內容範例：

```html
<p>我是<strong>姓名</strong>，職稱與專業描述。</p>
<ul>
  <li>專長領域 A</li>
  <li>專長領域 B</li>
</ul>
```

`.env` 中的 `SENDER_BIO_FILE` 指向此檔案的絕對路徑。修改內容後無需重啟服務。

### 5. 自訂郵件樣板

- **主旨**：`template/email_subject.txt`
- **內文**：`template/email_body.html.j2`

可用的 Jinja2 變數：

| 變數 | 說明 |
|---|---|
| `{{ sender_name }}` | 寄件人姓名（來自 `.env`） |
| `{{ sender_bio \| safe }}` | 個人簡介 HTML（來自 `SENDER_BIO_FILE` 指定的檔案） |
| `{{ event_name }}` | 活動名稱（使用者輸入） |
| `{{ recipient_name }}` | 對方姓名（名片擷取） |
| `{{ recipient_title }}` | 對方職稱 |
| `{{ company_name }}` | 對方公司 |

### 6. 啟動

```bash
# 開發模式（hot-reload）
uvicorn app.main:app --reload --port 8000

# 或直接啟動
python -m uvicorn app.main:app --port 8000
```

瀏覽 http://localhost:8000 → Google 登入 → 開始使用

---

## 使用流程

```
① 輸入活動名稱
② 拍攝名片（後鏡頭）或從相簿選取
③ 確認 AI 識別結果（可手動修正）
④ 一鍵寄出 Gmail 問候信
```

---

## 樣板格式說明

樣板使用 [Jinja2](https://jinja.palletsprojects.com/) 語法：

```html
<!-- 嵌入變數 -->
{{ recipient_name }}

<!-- HTML 內容輸出（自我介紹）-->
{{ sender_bio | safe }}

<!-- 條件判斷 -->
{% if recipient_title %}，{{ recipient_title }}{% endif %}
```

HTML 郵件樣板（`email_body.html.j2`）支援完整 HTML + CSS，
主流郵件客戶端（Gmail、Outlook、Apple Mail）皆能正確渲染。

---

## 已知限制與備註

- **Gmail token 有效期**：access token 約 1 小時，refresh token 在 Testing 模式下為 7 天；
  access token 過期時，Gmail SDK 會自動以 refresh token 換取新 token，
  並即時回寫至 session vault，使用者無需重登；
  refresh token 到期（7 天）時才需要登出重登
- **名片識別限制**：模糊或強烈反光的名片識別準確度會下降，建議在光線充足的環境拍攝；
  識別結果可在確認頁手動修正後再寄出
- **多使用者擴充**：目前白名單為單一 email；若未來需多人使用，改為 DB 白名單即可，
  核心架構不需改動