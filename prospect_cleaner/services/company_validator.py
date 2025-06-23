import json
import re
import math
from typing import List, Tuple
from openai import AsyncOpenAI
from prospect_cleaner.models.validation_result import ValidationResult
from prospect_cleaner.settings import settings
from prospect_cleaner.logconf import logger

class CompanyValidator:
    """
    Validates / normalises company names.

    ✱ Uses the OpenAI Response API with the web-search preview tool
    ✱ Keeps citations + long French explanation
    """

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key else None
        )

    @staticmethod
    def _parse_response(response) -> Tuple[List[str], str]:
        urls, texts = [], []
        for item in getattr(response, "output", []):
            if item.type != "message":
                continue
            for chunk in item.content:
                if hasattr(chunk, "text"):
                    texts.append(chunk.text.strip())
                for ann in getattr(chunk, "annotations", []):
                    if getattr(ann, "type", "") == "url_citation" and ann.url:
                        urls.append(ann.url)
        raw = "\n\n".join(texts)
        # strip JSON block if present
        data = {}
        m = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                data = {}
        for u in data.get("citations", []):
            if isinstance(u, str):
                urls.append(u)
        if "explication" in data and isinstance(data["explication"], str):
            expl = data["explication"]
        else:
            expl = re.sub(r"```json.*?```", "", raw, flags=re.DOTALL)
        expl = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", expl)
        expl = re.sub(r"^[\-\*\•]\s*", "", expl, flags=re.MULTILINE)
        explanation = " ".join(expl.split()).strip()
        return urls, explanation

    async def validate(self, company_input: str, email_domain: str = "") -> ValidationResult:
        company_input = (company_input or "").strip()
        if not self._client or not company_input:
            return ValidationResult(company_input, company_input, 0.0, "no_llm")

        messages = [
            {
                "role": "developer",
                "content": """
# Identity
You are an expert in global companies and commercial brands.

# Instructions
- Always perform a web search to identify the company.
- Ignore legal suffixes (SARL, SA, AG, etc.) when searching.
- Return the current publicly used trade name.
- If recently renamed, use the new name.
- For subsidiaries, use the main brand unless distinct.
- Evaluate confidence (0-1) on:
    • Certainty of identification
    • Match with email domain
    • Whether it’s well-known
- If not found, clean the name and mark unknown.
- Preserve special characters.
- Do not guess or invent.
- You MUST return a JSON object with:

{
    "nom_commercial": "Meta",
    "confidence": 0.95,
    "explication": "Nom officiel après changement en 2021.",
    "changement_nom": true,
    "entreprise_connue": true,
    "citations": ["https://example.com"]
}
"""
            },
            {
                "role": "user",
                "content": (
                    f'Entreprise: "{company_input}", '
                    f'Domaine email: "{email_domain if email_domain and email_domain != "nan" else "Non fourni"}"'
                )
            }
        ]

        try:
            response = await self._client.responses.create(
                model="gpt-4.1-mini",
                tools=[{
                    "type": "web_search_preview",
                    "user_location": {"type": "approximate", "country": "CH"},
                }],
                input=messages,
            )

            # === DÉBOGAGE : imprime la réponse brute ===
            print("=== [DEBUG] response.output_text ===")
            print(response.output_text)
            print("=== [DEBUG] response.output JSON blocks ===")

            # citations + explication textuelle
            urls, explanation = self._parse_response(response)
            citation_str = ";".join(urls) if urls else ""

            # essaie de parser directement output_text
            data = {}
            try:
                raw_txt = response.output_text.strip()
                raw_txt = re.sub(r"^```json\s*|\s*```$", "", raw_txt, flags=re.DOTALL)
                data = json.loads(raw_txt)
            except Exception as e:
                print(f"[DEBUG] échec json.loads sur output_text: {e}")
                data = {}

            print("=== [DEBUG] JSON parsé ===")
            print(data)

            # fallback si pas de nom_commercial
            if "nom_commercial" not in data:
                cleaned = self._basic_clean(company_input)
                conf = self._calibrate(0.5, len(urls), False, True)
                print(f"[DEBUG] fallback basic clean → '{cleaned}', conf={conf}")
                return ValidationResult(
                    company_input, cleaned, conf,
                    citation_str, explanation or "fallback basic clean"
                )

            nom_final = data["nom_commercial"]
            base_conf = float(data.get("confidence", 0.5))

            # signaux additionnels
            citations_n = len(urls)
            domain = re.sub(r"[^a-z0-9]", "",
                            (email_domain or "").lower().split("@")[-1].split(".")[0])
            domain_ok = bool(domain and domain in re.sub(r"[^a-z0-9]", "", nom_final.lower()))
            unknown = not data.get("entreprise_connue", True)

            confidence = self._calibrate(base_conf, citations_n, domain_ok, unknown)
            return ValidationResult(company_input, nom_final, confidence, citation_str, explanation)

        except Exception as e:
            logger.error("Company LLM error (%s): %s", company_input, e, exc_info=False)
            cleaned = self._basic_clean(company_input)
            return ValidationResult(company_input, cleaned, 0.3, "error", "exception fallback")

    @staticmethod
    def _calibrate(conf: float, citations: int, domain_match: bool, unknown_flag: bool) -> float:
        bonus = min(citations, 4) * 0.025
        if domain_match:
            bonus += 0.1
        if unknown_flag:
            conf *= 0.3
        raw = min(max(conf + bonus, 0), 1)
        # arrondi au centième supérieur
        return math.ceil(raw * 100) / 100

    @staticmethod
    def _basic_clean(name: str) -> str:
        patterns = [
            r"\s+(SARL|SAS|SA|SASU|EURL|SNC|SCI|SCP|SCOP|SEL|SELARL|SELAS|SELASU)",
            r"\s+(AG|GmbH|KG|OHG|GbR|UG)",
            r"\s+(Ltd|Limited|LLC|Inc|Incorporated|Corp|Corporation|Company|Co\.?)",
            r"\s+(BV|NV|VOF|CV)",
            r"\s+(SpA|Srl|Snc|Sas)",
            r"\s+(AB|HB|KB)",
            r"[,\s]+(®|™|©)",
            r"\s*\([^)]+\)$",
        ]
        cleaned = name.strip()
        for pat in patterns:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
        return " ".join(cleaned.split()) or name
