import json, re
from typing import List, Tuple
from openai import AsyncOpenAI
from prospect_cleaner.models.validation_result import ValidationResult
from prospect_cleaner.settings import settings
from prospect_cleaner.logconf import logger


class CompanyValidator:
    """
    Validates / normalises company names.

    ✱ Uses the OpenAI Response API with the web‑search preview tool
    ✱ Keeps citations + long French explanation
    """

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key else None
        )

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _parse_response(response) -> Tuple[List[str], str]:
        """
        Extract (urls, explanation) from the Response‑API object.
        Mirrors the logic in the old validator.py.
        """
        urls, texts = [], []

        # 1. Collect all message chunks + URL annotations
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

        # 2. If a full JSON block exists, parse it
        data = {}
        m = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                data = {}

        # 3. Add citations coming from the JSON
        for u in data.get("citations", []):
            if isinstance(u, str):
                urls.append(u)

        # 4. Pick the explanation string
        if "explication" in data and isinstance(data["explication"], str):
            expl = data["explication"]
        else:
            expl = re.sub(r"```json.*?```", "", raw, flags=re.DOTALL)

        # 5. Flatten explanation for CSV‑friendliness
        expl = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", expl)          # markdown links
        expl = re.sub(r"^[\-\*\•]\s*", "", expl, flags=re.MULTILINE)  # bullets
        explanation = " ".join(expl.split()).strip()

        return urls, explanation

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    async def validate(self, company_input: str, email_domain: str = "") -> ValidationResult:
        company_input = (company_input or "").strip()
        if not self._client or not company_input:
            return ValidationResult(company_input, company_input, 0.0, "no_llm")

        # ------------------------------------------------------------------ #
        # 1. Build messages exactly like the old code
        # ------------------------------------------------------------------ #
        messages = [
            {
                "role": "developer",
                "content": """
# Identity
You are an expert in global companies and commercial brands.

# Instructions
- Always perform a web search to identify the company.
- Ignore legal suffixes (SARL, SA, AG, etc.) when searching.
- Return the current public used trade name on the website of the company or its social media profiles.
- If the company has recently changed its name, use the new name.
- For subsidiaries, use the main brand unless the subsidiary has its own identity.
- Evaluate your confidence (0-1) based on:
    - Certainty of identification
    - Match with email domain
    - Whether the company is well-known
- If not found, clean the name and state the company is unknown.
- Preserve special characters in names.
- Do not guess or invent answers.
- Respond ONLY in JSON, including a "citations" field with URLs from the web search.

# Output Example
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
                ),
            },
        ]

        # ------------------------------------------------------------------ #
        # 2. Call the Response API with web_search_preview tool
        # ------------------------------------------------------------------ #
        try:
            response = await self._client.responses.create(
                model="gpt-4.1-mini",
                tools=[{
                    "type": "web_search_preview",
                    "user_location": {"type": "approximate", "country": "CH"},
                }],
                input=messages,
            )

            # 3. Parse citations + explanation
            urls, explanation = self._parse_response(response)
            citation_str = ";".join(urls) if urls else ""

            # 4. Try to load JSON content (may be in response.output_text)
            data = {}
            try:
                data = json.loads(response.output_text)
            except (TypeError, json.JSONDecodeError):
                pass

            # If JSON missing, fall back to a simple cleaned name
            if "nom_commercial" not in data:
                cleaned = self._basic_clean(company_input)
                return ValidationResult(company_input, cleaned, 0.3,
                                        citation_str, explanation or "fallback basic clean")

            nom_final  = data["nom_commercial"]
            confidence = float(data.get("confidence", 0.5))

            # 5. Domain bonus
            if email_domain and email_domain != "nan":
                dom         = email_domain.lower().split(".")[0]
                nom_sanit   = re.sub(r"[^a-z0-9]", "", nom_final.lower())
                if dom in nom_sanit or nom_sanit in dom:
                    confidence = min(confidence + 0.1, 1.0)

            return ValidationResult(
                original     = company_input,
                validated    = nom_final,
                confidence   = confidence,
                source       = citation_str,
                explanation  = explanation,
            )

        except Exception as e:
            logger.error("Company LLM error (%s): %s", company_input, e, exc_info=False)
            cleaned = self._basic_clean(company_input)
            return ValidationResult(company_input, cleaned, 0.3, "error", "exception fallback")

    # ------------------------------------------------------------------ #
    # Simple regex clean for hard errors
    # ------------------------------------------------------------------ #
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
