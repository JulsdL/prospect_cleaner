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

    async def validate(self, company_input: str, email_domain: str = "") -> ValidationResult:
        # Ensure company_input is a string and cleaned up
        if not isinstance(company_input, str):
            # Convert potential NaN (float) or None to empty string or "nan"
            company_input_str = str(company_input) if company_input is not None else ""
            if company_input_str.lower() == "nan": # Check for "nan" string irrespective of case
                company_input_str = "" # Treat actual "nan" strings (from NaN floats) as empty
        else:
            company_input_str = company_input

        company_input_str = company_input_str.strip()

        if not self._client or not company_input_str: # Check after ensuring it's a string
            # Pass original company_input for the first field of ValidationResult for fidelity
            return ValidationResult(company_input, company_input_str, 0.0, "no_llm")

        # All further processing uses company_input_str
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
- If not found, use the cleaned input name for `nom_commercial` and provide an explanation.
- Preserve special characters.
- Do not guess or invent.
- All textual explanations (`explication`) MUST be in French.

- CRITICAL REQUIREMENT: Your *entire response* MUST be a single, valid JSON object. Do NOT include any text, remarks, or explanations outside of this JSON object. Adhere strictly to the schema provided below.

- If the company is positively identified: Populate all fields as accurately as possible.
- If the company cannot be reliably found or information is ambiguous:
    - `nom_commercial` should be the original input company name, cleaned by basic legal suffix removal.
    - `confidence` MUST be low (e.g., less than 0.3).
    - `entreprise_connue` MUST be `false`.
    - `explication` should state that the company was not found or identified with certainty, in French.
    - `citations` should be an empty list or include URLs that explain the ambiguity/lack of information.
- Regardless of the outcome (found, not found, ambiguous), the output MUST be JSON.

JSON Schema:
{
    "nom_commercial": "string",
    "confidence": "float (0.0 to 1.0)",
    "explication": "string (in French)",
    "changement_nom": "boolean",
    "entreprise_connue": "boolean",
    "citations": ["list of strings (URLs)"]
}
"""
            },
            {
                "role": "user",
                "content": 'Entreprise: "Fantomas Widgets Introuvables SA", Domaine email: "contact@fantomas.xyz"'
            },
            {
                "role": "assistant",
                "content": """\
```json
{
    "nom_commercial": "Fantomas Widgets Introuvables",
    "confidence": 0.1,
    "explication": "L'entreprise 'Fantomas Widgets Introuvables SA' n'a pas pu être identifiée de manière fiable lors de la recherche. Le nom a été nettoyé des suffixes légaux.",
    "changement_nom": false,
    "entreprise_connue": false,
    "citations": []
}
```"""
            },
            {
                "role": "user",
                "content": (
                    f'Entreprise: "{company_input_str}", ' # Use the cleaned string version
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
            # print("=== [DEBUG] response.output JSON blocks ===") # No longer have separate JSON blocks

            data = {}
            explanation = "Failed to parse LLM response or extract key information."
            urls = []

            try:
                raw_txt = response.output_text.strip()
                # Attempt to extract JSON even if there's leading/trailing text,
                # though ideally the LLM returns JSON only as per the updated prompt.
                match = re.search(r"```json\s*(\{.*?\})\s*```", raw_txt, re.DOTALL)
                if match:
                    json_str = match.group(1)
                else:
                    # Assume the raw_txt is the JSON itself if no markdown block is found
                    json_str = raw_txt

                data = json.loads(json_str)
                print("=== [DEBUG] JSON parsé ===")
                print(data)

                explanation = data.get("explication", "Explication non fournie par l'IA.")
                raw_citations = data.get("citations", [])
                if isinstance(raw_citations, list):
                    urls = [str(c) for c in raw_citations if isinstance(c, str)]
                else:
                    urls = [] # or handle as an error/warning

            except Exception as e:
                print(f"[DEBUG] échec json.loads sur output_text: {e}")
                # data remains {}
                explanation = f"Erreur de parsing JSON: {e}"

            citation_str = ";".join(urls) if urls else ""

            if "nom_commercial" not in data or not data.get("nom_commercial"):
                cleaned_name = self._basic_clean(company_input_str) # Use cleaned string
                # Use a low, fixed confidence for this fallback.
                # The 'unknown_flag' for _calibrate would be True. Domain match is False.
                # Number of citations (urls) might be 0 if parsing failed before extracting them.
                conf = self._calibrate(0.1, len(urls), False, True)
                final_explanation = explanation if data else "Fallback: Nom nettoyé basiquement en raison d'une réponse invalide de l'IA."
                if not data.get("nom_commercial") and "nom_commercial" in data : # specifically if nom_commercial was empty
                    final_explanation = "Nom commercial non fourni par l'IA, utilisation du nom nettoyé."

                print(f"[DEBUG] fallback basic clean → '{cleaned_name}', conf={conf}, explanation: {final_explanation}")
                return ValidationResult(
                    company_input, cleaned_name, conf, # original_input is company_input
                    citation_str, final_explanation
                )

            nom_final = data["nom_commercial"]
            base_conf = float(data.get("confidence", 0.5)) # LLM's self-assessed confidence

            # Signaux additionnels pour calibration
            # urls list is already populated from JSON data's "citations"
            domain = re.sub(r"[^a-z0-9]", "",
                            (email_domain or "").lower().split("@")[-1].split(".")[0])
            # Check if the (cleaned) domain appears in the (cleaned) final name
            cleaned_nom_final_for_domain_check = re.sub(r"[^a-z0-9]", "", nom_final.lower())
            domain_ok = bool(domain and domain in cleaned_nom_final_for_domain_check)

            # `entreprise_connue` comes from the JSON, default to True if missing (conservative)
            # but prompt now guides LLM to set this, if it's missing, it's more likely an issue.
            # Let's default to unknown (True for unknown_flag) if not present.
            unknown_flag = not data.get("entreprise_connue", False) # If 'entreprise_connue':false, unknown_flag = true

            confidence = self._calibrate(base_conf, len(urls), domain_ok, unknown_flag)
            return ValidationResult(company_input, nom_final, confidence, citation_str, explanation) # original_input is company_input

        except Exception as e:
            logger.error("Company LLM error during validation call for '%s': %s", company_input_str, e, exc_info=True) # Log cleaned string
            cleaned = self._basic_clean(company_input_str) # Use cleaned string
            return ValidationResult(company_input, cleaned, 0.3, "error", "exception fallback") # original_input is company_input

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
- If not found, use the cleaned input name for `nom_commercial` and provide an explanation.
- Preserve special characters.
- Do not guess or invent.
- All textual explanations (`explication`) MUST be in French.
- You MUST return *only* a JSON object. Do not include any other text or explanations outside the JSON structure. The JSON object should conform to this schema:

{
    "nom_commercial": "Meta",
    "confidence": 0.95,
    "explication": "Nom officiel après changement en 2021.",
    "changement_nom": true,
    "entreprise_connue": true,
    "citations": ["https://example.com"]
}

If the company is not found, `nom_commercial` should be the cleaned input company name, `confidence` should be low (e.g., < 0.3), and `entreprise_connue` should be `false`.
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
            # print("=== [DEBUG] response.output JSON blocks ===") # No longer have separate JSON blocks

            data = {}
            explanation = "Failed to parse LLM response or extract key information."
            urls = []

            try:
                raw_txt = response.output_text.strip()
                # Attempt to extract JSON even if there's leading/trailing text,
                # though ideally the LLM returns JSON only as per the updated prompt.
                match = re.search(r"```json\s*(\{.*?\})\s*```", raw_txt, re.DOTALL)
                if match:
                    json_str = match.group(1)
                else:
                    # Assume the raw_txt is the JSON itself if no markdown block is found
                    json_str = raw_txt

                data = json.loads(json_str)
                print("=== [DEBUG] JSON parsé ===")
                print(data)

                explanation = data.get("explication", "Explication non fournie par l'IA.")
                raw_citations = data.get("citations", [])
                if isinstance(raw_citations, list):
                    urls = [str(c) for c in raw_citations if isinstance(c, str)]
                else:
                    urls = [] # or handle as an error/warning

            except Exception as e:
                print(f"[DEBUG] échec json.loads sur output_text: {e}")
                # data remains {}
                explanation = f"Erreur de parsing JSON: {e}"

            citation_str = ";".join(urls) if urls else ""

            if "nom_commercial" not in data or not data.get("nom_commercial"):
                cleaned_name = self._basic_clean(company_input)
                # Use a low, fixed confidence for this fallback.
                # The 'unknown_flag' for _calibrate would be True. Domain match is False.
                # Number of citations (urls) might be 0 if parsing failed before extracting them.
                conf = self._calibrate(0.1, len(urls), False, True)
                final_explanation = explanation if data else "Fallback: Nom nettoyé basiquement en raison d'une réponse invalide de l'IA."
                if not data.get("nom_commercial") and "nom_commercial" in data : # specifically if nom_commercial was empty
                    final_explanation = "Nom commercial non fourni par l'IA, utilisation du nom nettoyé."

                print(f"[DEBUG] fallback basic clean → '{cleaned_name}', conf={conf}, explanation: {final_explanation}")
                return ValidationResult(
                    company_input, cleaned_name, conf,
                    citation_str, final_explanation
                )

            nom_final = data["nom_commercial"]
            base_conf = float(data.get("confidence", 0.5)) # LLM's self-assessed confidence

            # Signaux additionnels pour calibration
            # urls list is already populated from JSON data's "citations"
            domain = re.sub(r"[^a-z0-9]", "",
                            (email_domain or "").lower().split("@")[-1].split(".")[0])
            # Check if the (cleaned) domain appears in the (cleaned) final name
            cleaned_nom_final_for_domain_check = re.sub(r"[^a-z0-9]", "", nom_final.lower())
            domain_ok = bool(domain and domain in cleaned_nom_final_for_domain_check)

            # `entreprise_connue` comes from the JSON, default to True if missing (conservative)
            # but prompt now guides LLM to set this, if it's missing, it's more likely an issue.
            # Let's default to unknown (True for unknown_flag) if not present.
            unknown_flag = not data.get("entreprise_connue", False) # If 'entreprise_connue':false, unknown_flag = true

            confidence = self._calibrate(base_conf, len(urls), domain_ok, unknown_flag)
            return ValidationResult(company_input, nom_final, confidence, citation_str, explanation)

        except Exception as e:
            logger.error("Company LLM error during validation call for '%s': %s", company_input, e, exc_info=True)
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
