import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.config import get_settings

logger = logging.getLogger(__name__)


class GmailService:
    def __init__(self):
        self.settings = get_settings()

    def _build_gmail_client(
        self, access_token: str, refresh_token: str | None = None
    ) -> tuple:
        """
        用 OAuth2 token 建立 Gmail API client
        回傳 (service, creds) tuple，供呼叫端在寄信後檢查 token 是否被刷新
        """
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return service, creds

    def _create_mime_message(
        self,
        sender_email: str,
        recipient_email: str,
        subject: str,
        html_body: str,
    ) -> str:
        message = MIMEMultipart("alternative")
        message["From"] = f"{self.settings.sender_name} <{sender_email}>"
        message["To"] = recipient_email
        message["Subject"] = subject

        plain_text = "此郵件為 HTML 格式，請使用支援 HTML 的郵件客戶端查看。"
        message.attach(MIMEText(plain_text, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

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
    ) -> tuple[dict, str]:
        """
        透過 Gmail API 寄送 HTML 郵件

        Returns:
            (result, current_access_token)
            current_access_token：寄信後 SDK 實際使用的 token
            若 SDK 在過程中自動刷新了 token，此值會與傳入的 access_token 不同
            呼叫端應比對差異並決定是否回寫 session vault
        Raises:
            HttpError: Gmail API 呼叫失敗
            ValueError: recipient_email 為空
        """
        if not recipient_email:
            raise ValueError("Recipient email is required but was empty.")

        service, creds = self._build_gmail_client(access_token, refresh_token)
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
            # creds.token 是 SDK 執行後實際使用的 token
            # 若發生自動刷新，此值已更新為新 token
            return result, creds.token
        except HttpError as e:
            logger.error(f"Gmail API error: {e}")
            raise
