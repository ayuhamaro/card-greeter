# 名片問候助理 · Business Card Greeter

新創交流活動的一鍵問候工具：拍名片 → AI 識別 → 查詢公司 → Gmail 寄信

由 **Claude** 實作、**Gemini** 擔任安全審查。

---

## 架構概覽

```
FastAPI Backend
├── /auth/*                  Google OAuth2 登入 / 白名單驗證 / session
├── /api/scan                GPT-5.5 Vision 名片 OCR（Structured Outputs）
├── /api/company-lookup      Gemini Grounding 查詢公司業務資料（手動觸發）
├── /api/collaboration-hint  GPT-5.5 生成合作機會描述
├── /api/send                Jinja2 渲染樣板 + Gmail API 寄信
│                            └── [選用] 寄信成功後背景發布 Pub/Sub 事件
└── /api/save-contact        Google People API 新增聯絡人

Frontend (SPA)
└── static/index.html   手機相機拍攝 + 4 步驟流程 UI

Session 安全設計
├── OAuth2 token       Fernet 對稱加密後存入 cookie（vault）
├── picture URL        不存入 session，改由前端 sessionStorage 快取
├── token 刷新         Gmail SDK 自動刷新後回寫 vault，無需重登
├── SSL Termination    ProxyHeadersMiddleware 確保 Nginx 後方的 https 上下文正確傳遞
└── 全域例外隔離       global_exception_handler 確保 traceback 不流出至 HTTP response

前端安全設計
└── XSS 防禦          Grounding 來源 URL 改用 DOM API 動態建立節點，
                      嚴格驗證 http/https 協議，阻斷 javascript: 偽協議注入
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
   - Scopes 加入：`userinfo.email`、`userinfo.profile`、`openid`、`gmail.send`、`contacts`
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
| `OPENAI_VISION_MODEL` | 名片識別模型（預設 `gpt-5.5`） | — |
| `OPENAI_COLLAB_MODEL` | 合作機會生成模型（預設 `gpt-5.5`） | — |
| `GEMINI_API_KEY` | Gemini API 金鑰（公司查詢 Grounding 用） | — |
| `GEMINI_GROUNDING_MODEL` | Grounding 模型（預設 `gemini-2.5-flash`） | — |
| `GOOGLE_CLIENT_ID` | GCP OAuth2 Client ID | — |
| `GOOGLE_CLIENT_SECRET` | GCP OAuth2 Client Secret | — |
| `SESSION_SECRET_KEY` | Session 簽章金鑰 | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_ENCRYPT_KEY` | Session Token 加密金鑰（Fernet） | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SENDER_NAME` | 寄件人姓名 | — |
| `SENDER_BIO_FILE` | 自我介紹 HTML 檔案的絕對路徑 | — |
| `COLLABORATION_HINTS_FILE` | 合作機會準則 YAML 檔案的絕對路徑 | — |
| `ALLOWED_EMAIL` | 唯一允許登入的 Gmail | — |
| `APP_BASE_URL` | 本機開發用 `http://localhost:8000` | — |
| `GITHUB_REPO_URL` | 郵件 Footer 的 GitHub Repo 連結 | — |
| `PUBSUB_ENABLED` | 啟用 Pub/Sub 事件發布（預設 `false`） | — |
| `GOOGLE_SA_CREDENTIALS_FILE` | Service Account JSON 金鑰檔的絕對路徑 | — |
| `PUBSUB_PROJECT_ID` | GCP 專案 ID | — |
| `PUBSUB_TOPIC_ID` | Pub/Sub Topic 名稱 | — |

### 4. 建立個人設定檔案（必填）

以下檔案存放個人資料，不進入 repo，統一放於 `config/` 目錄：

**自我介紹（HTML 格式）：**

```bash
mkdir -p /path/to/config
vim /path/to/config/sender_bio.html
```

```html
<p>我是<strong>姓名</strong>，職稱與專業描述。</p>
<ul>
  <li>專長領域 A</li>
  <li>專長領域 B</li>
</ul>
```

**合作機會準則（YAML 格式）：**

```bash
vim /path/to/config/collaboration_hints.yaml
```

```yaml
default: "探索雙方在 AI 應用與數位轉型上的合作可能"

categories:
  tech: "技術整合、API 串接、共同開發產品功能"
  consulting: "顧問合作、專案外包、知識移轉"
  ai: "AI 模型應用、資料分析、智慧化流程導入"
  # 可自由新增 category，調整後無需重啟服務
```

GPT 會根據 Gemini 查到的公司業務資料自動判斷 category，再以對應準則生成合作機會描述。若業務不明確，自動使用 `default`。

> **模型相容性備註**
> GPT-4 系列使用 `max_tokens`；GPT-5 系列（含 GPT-5.5）改用 `max_completion_tokens`。
> 程式碼已統一使用 `max_completion_tokens`，支援 `gpt-4o`、`gpt-4o-mini`、`gpt-5.5`、`gpt-5.5-2026-04-23`。
> 切換模型只需修改 `.env` 中的對應欄位並重啟服務，不需要動程式碼。

### 5. 設定 Pub/Sub（選用）

寄信成功後可在背景將名片資料發布至 Google Cloud Pub/Sub，供下游系統接收處理。

**GCP 前置作業：**

```bash
# 建立 Topic
gcloud pubsub topics create card-greeter-events --project=<your-project-id>

# 建立 Service Account 並授予 Publisher 角色
gcloud iam service-accounts create card-greeter-pubsub \
  --project=<your-project-id>

gcloud projects add-iam-policy-binding <your-project-id> \
  --member="serviceAccount:card-greeter-pubsub@<your-project-id>.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# 下載 JSON 金鑰
gcloud iam service-accounts keys create sa.json \
  --iam-account=card-greeter-pubsub@<your-project-id>.iam.gserviceaccount.com
```

**金鑰檔部署（建議放在專案目錄的平行目錄）：**

```bash
sudo mkdir -p /var/www/secrets
sudo cp sa.json /var/www/secrets/card-greeter-pubsub-sa.json
sudo chown <service-user>:<service-user> /var/www/secrets
chmod 700 /var/www/secrets
chmod 600 /var/www/secrets/card-greeter-pubsub-sa.json
```

放在 `/var/www/secrets/` 而非專案目錄內，可避免 Nginx 設定失誤意外暴露金鑰，且可跨專案共用。金鑰輪替時只需替換檔案並重啟服務。

**`.env` 設定：**

```
PUBSUB_ENABLED=true
GOOGLE_SA_CREDENTIALS_FILE=/var/www/secrets/card-greeter-pubsub-sa.json
PUBSUB_PROJECT_ID=<your-project-id>
PUBSUB_TOPIC_ID=card-greeter-events
```

**發布的訊息格式：**

```json
{
  "sent_at": "2026-06-01T14:21:45+08:00",
  "sender_email": "sender@gmail.com",
  "sender_line_id": "your_line_id",
  "event_name": "活動名稱",
  "card": { "name": "...", "title": "...", "company": "...", ... },
  "collaboration_hints": "YAML 全文快照"
}
```

### 7. 自訂郵件樣板

- **主旨**：`template/email_subject.txt`
- **內文**：`template/email_body.html.j2`

可用的 Jinja2 變數：

| 變數 | 說明 |
|---|---|
| `{{ sender_name }}` | 寄件人姓名（來自 `.env`） |
| `{{ sender_bio \| safe }}` | 個人簡介 HTML（來自 `SENDER_BIO_FILE`） |
| `{{ event_name }}` | 活動名稱（使用者輸入） |
| `{{ recipient_name }}` | 對方姓名（名片擷取） |
| `{{ recipient_title }}` | 對方職稱 |
| `{{ company_name }}` | 對方公司 |
| `{{ collaboration_hint }}` | 合作機會描述（選填，空值不渲染） |
| `{{ github_repo_url }}` | GitHub Repo 連結（來自 `.env`） |

### 8. 啟動

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
④ 選用：點擊「查詢公司資料」→ 顯示公司簡介與合作機會描述（可編輯或清空）
⑤ 一鍵寄出 Gmail 問候信
⑥ 選用：點擊「將名片資料存入聯絡人」→ 確認欄位後存入 Google 聯絡人
```

---

## 樣板格式說明

樣板使用 [Jinja2](https://jinja.palletsprojects.com/) 語法：

```html
<!-- 嵌入變數 -->
{{ recipient_name }}

<!-- HTML 內容輸出（自我介紹）-->
{{ sender_bio | safe }}

<!-- 條件判斷（合作機會選填） -->
{% if collaboration_hint %}
<div>{{ collaboration_hint }}</div>
{% endif %}
```

HTML 郵件樣板（`email_body.html.j2`）支援完整 HTML + CSS，
主流郵件客戶端（Gmail、Outlook、Apple Mail）皆能正確渲染。

---

## 已知限制與備註

- **Gmail token 有效期**：access token 約 1 小時，refresh token 在 Testing 模式下為 7 天；
  access token 過期時，Gmail SDK 會自動以 refresh token 換取新 token，
  並即時回寫至 session vault，使用者無需重登；
  refresh token 到期（7 天）時才需要登出重登
- **名片識別語言優先級**：名片同時有中英文時，優先擷取中文姓名、公司名稱與職稱
- **名片識別限制**：模糊或強烈反光的名片識別準確度會下降，建議在光線充足的環境拍攝；
  識別結果可在確認頁手動修正後再寄出
- **公司查詢覆蓋率**：Gemini Grounding 對知名企業查詢效果最佳；查無資料時合作機會描述
  會自動 fallback 至 `collaboration_hints.yaml` 的 `default` 項目
- **多使用者擴充**：目前白名單為單一 email；若未來需多人使用，改為 DB 白名單即可，
  核心架構不需改動