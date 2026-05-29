import logging
from datetime import date
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.config import get_settings
from app.models import SaveContactRequest

logger = logging.getLogger(__name__)


class ContactsService:
    def __init__(self):
        self.settings = get_settings()

    def _build_people_client(
        self, access_token: str, refresh_token: str | None = None
    ) -> tuple:
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
            scopes=["https://www.googleapis.com/auth/contacts"],
        )
        service = build("people", "v1", credentials=creds, cache_discovery=False)
        return service, creds

    def _build_contact_body(self, req: SaveContactRequest) -> dict:
        body: dict = {}

        if req.first_name or req.last_name:
            body["names"] = [{"givenName": req.first_name, "familyName": req.last_name}]

        if req.email:
            body["emailAddresses"] = [{"value": req.email}]

        phones = []
        if req.phone:
            phones.append({"value": req.phone, "type": "work"})
        if req.mobile:
            phones.append({"value": req.mobile, "type": "mobile"})
        if phones:
            body["phoneNumbers"] = phones

        if req.company or req.title:
            body["organizations"] = [{"name": req.company, "title": req.title}]

        addr = req.address
        if addr and any([addr.street, addr.city, addr.region, addr.postal_code, addr.country]):
            body["addresses"] = [{
                "streetAddress": addr.street,
                "city": addr.city,
                "region": addr.region,
                "postalCode": addr.postal_code,
                "country": addr.country,
                "type": "work",
            }]

        if req.website:
            body["urls"] = [{"value": req.website, "type": "work"}]

        if req.notes:
            body["biographies"] = [{"value": req.notes, "contentType": "TEXT_PLAIN"}]

        today = date.today()
        body["events"] = [{
            "date": {"year": today.year, "month": today.month, "day": today.day},
            "type": "anniversary",
        }]

        return body

    async def save_contact(
        self,
        access_token: str,
        refresh_token: str | None,
        req: SaveContactRequest,
    ) -> tuple[dict, str]:
        """
        透過 Google People API 建立新聯絡人
        Returns: (result, current_access_token)
        """
        service, creds = self._build_people_client(access_token, refresh_token)
        body = self._build_contact_body(req)
        result = service.people().createContact(body=body).execute()
        logger.info(f"Contact created: {result.get('resourceName')}")
        return result, creds.token
