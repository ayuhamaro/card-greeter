import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.config import get_settings

logger = logging.getLogger(__name__)

# INVARIANT: access_token 進入此 service 前，已通過 auth_router 驗證
# INVARIANT: recipient_email 必須是有效格式（由 CardInfo.email 提供）


class GmailService:
    def __init__(self):
        self.settings = get_settings()

    def _build_gmail_client(self, access_token: str, refresh_token: str | None = None):
        """
        用 OAuth2 token 建立 Gmail API client
        注意：token 存放在 session，不持久化到 DB（個人單用戶版本）
        """
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _create_mime_message(
        self,
        sender_email: str,
        recipient_email: str,
        subject: str,
        html_body: str,
    ) -> str:
        """
        建立 MIME multipart 郵件，並轉換為 Gmail API 所需的 base64url 格式
        """
        message = MIMEMultipart("alternative")
        message["From"] = f"{self.settings.sender_name} <{sender_email}>"
        message["To"] = recipient_email
        message["Subject"] = subject

        # 純文字備援（部分郵件客戶端不支援 HTML）
        plain_text = "此郵件為 HTML 格式，請使用支援 HTML 的郵件客戶端查看。"
        message.attach(MIMEText(plain_text, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

        # Gmail API 要求 base64url encoding（不是標準 base64）
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        return encoded

    async def send_email(
        self,
        access_token: str,
        sender_email: str,
        recipient_email: str,
        subject: str,
        html_body: str,
        refresh_token: str | None = None,
    ) -> dict:
        """
        透過 Gmail API 寄送 HTML 郵件
        
        Args:
            access_token: 使用者的 Gmail OAuth2 access token
            sender_email: 寄件人 Gmail 地址
            recipient_email: 收件人 email（從名片擷取）
            subject: 渲染後的郵件主旨
            html_body: 渲染後的 HTML 郵件內容
            refresh_token: 可選，用於 token 自動更新
        Returns:
            dict: Gmail API 回傳的 message object（含 id）
        Raises:
            HttpError: Gmail API 呼叫失敗
            ValueError: recipient_email 為空
        """
        if not recipient_email:
            raise ValueError("Recipient email is required but was empty.")

        service = self._build_gmail_client(access_token, refresh_token)
        encoded_message = self._create_mime_message(
            sender_email=sender_email,
            recipient_email=recipient_email,
            subject=subject,
            html_body=html_body,
        )

        try:
            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": encoded_message})
                .execute()
            )
            logger.info(f"Email sent successfully. Message ID: {result.get('id')}")
            return result
        except HttpError as e:
            logger.error(f"Gmail API error: {e}")
            raise
