import json, re, math
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
    # OpenAI Response API with web_search_preview tool
    # --------------------------------------------------------------------- #

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
        - Return the current publicly used trade name on the website of the company or its social media profiles, instead of it's legally registered name, it may differ !
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

            # 4. Reconstruire tout le texte brut et extraire le JSON block
            raw_chunks: list[str] = []
            for item in getattr(response, "output", []):
                if item.type != "message":
                    continue
                for chunk in item.content:
                    if hasattr(chunk, "text"):
                        raw_chunks.append(chunk.text)
            raw = "\n".join(raw_chunks)

            # 5. Charger strictement le bloc JSON
            data = {}
            m = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    data = {}


            # If JSON missing, fall back to a simple cleaned name
            if "nom_commercial" not in data:
                cleaned = self._basic_clean(company_input)
                return ValidationResult(company_input, cleaned, 0.3,
                                        citation_str, explanation or "fallback basic clean")

            nom_final  = data["nom_commercial"]
            base_confidence = float(data.get("confidence", 0.5))

            # 7) signaux additionnels
            citations_n = len(urls)
            domain_clean = re.sub(r"[^a-z0-9]", "",
                                (email_domain or "").lower().split("@")[-1].split(".")[0])
            domain_ok = bool(domain_clean) and domain_clean in re.sub(r"[^a-z0-9]", "", nom_final.lower())
            unknown   = not data.get("entreprise_connue", True)

            # 8) calibration finale
            confidence = self._calibrate(base_confidence, citations_n, domain_ok, unknown)

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
    # Confidence calibration
    # ------------------------------------------------------------------ #
    @staticmethod
    def _calibrate(conf: float,
                citations: int,
                domain_match: bool,
                unknown_flag: bool) -> float:
        """
        - citations jusqu'à +0.1 (4 liens = bonus max)
        - domain match       +0.1
        - inconnue          x0.3 (forte pénalité)
        """
        bonus = min(citations, 4) * 0.025          # 0→0, 4→0.1
        if domain_match:
            bonus += 0.1
        if unknown_flag:
            conf = conf * 0.3                      # réduit à 30 %
        raw = min(max(conf + bonus, 0), 1)
        # arrondi à l’entier supérieur sur deux décimales
        return math.ceil(raw * 100) / 100



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
