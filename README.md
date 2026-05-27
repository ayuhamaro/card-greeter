# 名片問候助理 · Business Card Greeter

新創交流活動的一鍵問候工具：拍名片 → AI 識別 → Gmail 寄信

---

## 架構概覽

```
FastAPI Backend
├── /auth/*          Google OAuth2 登入 / 白名單驗證 / session
├── /api/scan        GPT-4o Vision 名片 OCR
└── /api/send        Jinja2 渲染樣板 + Gmail API 寄信

Frontend (SPA)
└── static/index.html   手機相機拍攝 + 4步驟流程 UI
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
3. 啟用 API：
   - **Gmail API**（左側 API Library 搜尋啟用）
   - **Google+ API** 或 **People API**（取得 userinfo）
4. 建立 OAuth 2.0 憑證：
   - 類型：**Web application**
   - Authorized redirect URIs 加入：`http://localhost:8000/auth/callback`
5. 下載 Client ID 與 Client Secret，填入 `.env`

### 3. 設定 `.env`

```bash
cp .env .env.local    # 複製範本
```

填入以下欄位（參考 `.env` 註解）：
- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
- `SESSION_SECRET_KEY`（執行 `python -c "import secrets; print(secrets.token_hex(32))"` 生成）
- `SENDER_NAME` / `SENDER_BIO`
- `ALLOWED_EMAIL`（你的 Gmail，只有此帳號能登入）
- `APP_BASE_URL`（本機開發用 `http://localhost:8000`）

### 4. 自訂郵件樣板

- **主旨**：`template/email_subject.txt`
- **內文**：`template/email_body.html.j2`

可用的 Jinja2 變數：

| 變數 | 說明 |
|---|---|
| `{{ sender_name }}` | 寄件人姓名（來自 `.env`） |
| `{{ sender_bio }}` | 個人簡介（來自 `.env`） |
| `{{ event_name }}` | 活動名稱（使用者輸入） |
| `{{ recipient_name }}` | 對方姓名（名片擷取） |
| `{{ recipient_title }}` | 對方職稱 |
| `{{ company_name }}` | 對方公司 |

### 5. 啟動

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

## 部署（選用）

### Railway / Render 部署

1. 將專案推上 GitHub
2. 在平台設定 Environment Variables（同 `.env` 內容）
3. 更新 `.env` 中 `APP_BASE_URL` 為正式 domain
4. 在 Google Cloud Console 加入正式 domain 的 redirect URI：
   `https://yourdomain.com/auth/callback`

### 注意事項

- 生產環境務必使用 HTTPS（SessionMiddleware 的 `https_only=True` 已自動判斷）
- Gmail API 每日上限 500 封寄送，個人交流用途完全足夠

---

## 樣板格式說明

樣板使用 [Jinja2](https://jinja.palletsprojects.com/) 語法：

```html
<!-- 嵌入變數 -->
{{ recipient_name }}

<!-- 條件判斷（可用於樣板） -->
{% if recipient_title %}，{{ recipient_title }}{% endif %}
```

HTML 郵件樣板（`email_body.html.j2`）支援完整 HTML + CSS inline style，
大多數主流郵件客戶端（Gmail、Outlook、Apple Mail）皆能正確渲染。

---

## 已知限制與備註

- **Token 有效期**：Gmail access token 約 1 小時，session 設 8 小時內若 token 過期，
  登出重登即可取得新 token（refresh_token 已儲存，未來可加入自動刷新邏輯）
- **名片識別限制**：極度模糊、反光嚴重的名片識別準確度會下降，建議在光線充足的環境拍攝
- **多使用者擴充**：目前白名單為單一 email；若未來需多人使用，改為 DB 白名單即可，
  核心架構不需改動
