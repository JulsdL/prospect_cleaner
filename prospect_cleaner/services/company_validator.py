import json, re
from typing import Optional
from openai import AsyncOpenAI
from prospect_cleaner.models.validation_result import ValidationResult
from prospect_cleaner.settings import settings
from prospect_cleaner.logconf import logger

class CompanyValidator:
    """
    Splits LLM logic into its own file.
    """

    _prompt = """
Tu es un expert des entreprises.
Analyse: "{raw}"
Réponds uniquement JSON:
{{
  "nom_commercial": "…",
  "confidence": 0.9
}}
"""

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key else None
        )

    async def validate(self, raw: str, email_domain: str = "") -> ValidationResult:
        raw = (raw or "").strip()
        if not self._client or not raw:
            return ValidationResult(raw, raw, 0.0, "no_llm")

        try:
            msg = self._prompt.format(raw=raw)
            resp = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": msg}],
                temperature=0.2,
                max_tokens=300,
            )
            txt = resp.choices[0].message.content.strip()
            txt = re.sub(r"^```json|```$", "", txt).strip()
            data = json.loads(txt)

            conf = float(data["confidence"])
            # small bonus if domain matches
            dom = email_domain.split("@")[-1].split(".")[0] if email_domain else ""
            if dom and dom.lower() in data["nom_commercial"].lower():
                conf = min(conf + 0.1, 1.0)

            return ValidationResult(
                original=raw,
                validated=data["nom_commercial"],
                confidence=conf,
                source="gpt4",
            )
        except Exception as e:
            logger.error("Company LLM error (%s): %s", raw, e, exc_info=False)
            return ValidationResult(raw, raw, 0.0, "error")
