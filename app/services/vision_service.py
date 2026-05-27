import base64
import json
import re
import logging
from openai import AsyncOpenAI
from app.config import get_settings
from app.models import CardInfo

logger = logging.getLogger(__name__)

# INVARIANT: image_data 進入此 service 前，必須是有效的 base64 data URL
# INVARIANT: 回傳的 CardInfo.name 永遠不為空（GPT 若無法識別則回傳 "Unknown"）

EXTRACTION_PROMPT = """你是一個專業的名片資訊擷取工具。
請從這張名片圖片中擷取以下欄位，並以 JSON 格式回傳：

{
  "name": "姓名（必填，若無法識別填 'Unknown'）",
  "title": "職稱（若無則填空字串）",
  "email": "電子郵件（若無則填空字串）",
  "company": "公司名稱（若無則填空字串）",
  "raw_text": "名片上所有文字的完整 OCR 結果（換行用 \\n）"
}

規則：
- 只回傳 JSON，不要任何解釋文字
- 中英文名片皆支援
- email 必須是有效格式，否則填空字串
- 若名片上有多個姓名，取最顯眼（字體最大）的
"""


class VisionService:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    def _strip_data_url_prefix(self, image_data: str) -> tuple[str, str]:
        """
        從 data URL 分離 media_type 與純 base64 data
        e.g. "data:image/jpeg;base64,/9j/..." → ("image/jpeg", "/9j/...")
        """
        if image_data.startswith("data:"):
            match = re.match(r"data:([^;]+);base64,(.+)", image_data, re.DOTALL)
            if match:
                return match.group(1), match.group(2)
        # 若直接是純 base64（無前綴），預設 jpeg
        return "image/jpeg", image_data

    async def extract_card_info(self, image_data: str) -> CardInfo:
        """
        呼叫 GPT-4o Vision，從名片圖片擷取結構化聯絡資訊
        
        Args:
            image_data: base64 data URL (data:image/jpeg;base64,...)
        Returns:
            CardInfo: 結構化名片資訊
        Raises:
            ValueError: GPT 回傳無法解析的內容
            openai.APIError: API 呼叫失敗
        """
        media_type, b64_data = self._strip_data_url_prefix(image_data)

        # 驗證 base64 有效性
        try:
            base64.b64decode(b64_data, validate=True)
        except Exception as e:
            raise ValueError(f"Invalid base64 image data: {e}")

        logger.info("Calling GPT-4o Vision for card extraction...")

        response = await self.client.chat.completions.create(
            model="gpt-4o",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{b64_data}",
                                "detail": "high",  # 高解析度模式，確保小字體名片可讀
                            },
                        },
                        {
                            "type": "text",
                            "text": EXTRACTION_PROMPT,
                        },
                    ],
                }
            ],
        )

        raw_content = response.choices[0].message.content.strip()
        logger.debug(f"GPT-4o raw response: {raw_content}")

        # 清理可能的 markdown code fence
        clean_content = re.sub(r"```(?:json)?\s*|\s*```", "", raw_content).strip()

        try:
            data = json.loads(clean_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT response as JSON: {raw_content}")
            raise ValueError(f"GPT returned non-JSON response: {e}")

        # 確保 name 不為空
        if not data.get("name") or data["name"] == "":
            data["name"] = "Unknown"

        return CardInfo(**data)
