import logging
from google import genai
from google.genai import types
from app.config import get_settings

logger = logging.getLogger(__name__)


class CompanyService:
    def __init__(self):
        settings = get_settings()
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_grounding_model

    async def lookup(self, company_name: str) -> dict:
        """
        用 Gemini Grounding with Google Search 查詢公司資料

        Prompt 設計原則：
        - 明確限定只查業務相關資訊（主要業務、產品服務、市場定位）
        - 排除新聞、爭議事件、社會輿論，避免炎上事件汙染查詢結果
        - 限縮範疇同時也縮小 Prompt Injection 的攻擊面：
          惡意網頁內容即便被 Gemini 抓到，也因為與業務描述無關而被過濾

        Returns:
            {
                "summary": str,      # 公司業務簡介
                "sources": list[str] # grounding 來源 URL
            }
        """
        prompt = (
            f"請用繁體中文簡介「{company_name}」這間公司的業務資訊，"
            f"只需涵蓋：主要業務、產品或服務、市場定位與客群。"
            f"約 100 字以內，聚焦業務本身即可。"
            f"請勿包含新聞事件、爭議事件、社會輿論或任何非業務相關內容。"
            f"若查不到相關業務資料，請直接說明查無結果。"
        )

        logger.info(f"Gemini Grounding lookup: {company_name}")

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        summary = response.text or "查無相關公司資料。"

        # 擷取 grounding 來源 URL
        sources = []
        try:
            metadata = response.candidates[0].grounding_metadata
            if metadata and metadata.grounding_chunks:
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        sources.append(chunk.web.uri)
        except (AttributeError, IndexError):
            pass

        logger.info(f"Grounding complete. sources={len(sources)}")
        return {"summary": summary, "sources": sources[:3]}
