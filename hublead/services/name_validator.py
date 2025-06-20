import json, re
from typing import Tuple
from openai import AsyncOpenAI
from hublead.models.validation_result import ValidationResult
from hublead.settings import settings
from hublead.logconf import logger

class NameValidator:
    """Isolated service ─ can be mocked in tests."""

    _prompt_tmpl = """
Analyse et corrige si nécessaire ces informations de nom/prénom :
Nom: "{nom}"
Prénom: "{prenom}"

Points à vérifier :
- Inversion nom/prénom
- Noms composés mal séparés
- Noms multiculturels

Réponds UNIQUEMENT en JSON :
{{
  "nom_corrige": "…",
  "prenom_corrige": "…",
  "confidence_nom": 0.9,
  "confidence_prenom": 0.9
}}
"""

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key else None
        )

    async def validate(
        self, nom: str, prenom: str
    ) -> Tuple[ValidationResult, ValidationResult]:
        nom, prenom = (nom or "").strip(), (prenom or "").strip()
        if not self._client or not (nom or prenom):
            return (
                ValidationResult(nom, nom, 0.0, "no_llm"),
                ValidationResult(prenom, prenom, 0.0, "no_llm"),
            )

        prompt = self._prompt_tmpl.format(nom=nom, prenom=prenom)
        try:
            resp = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            txt = resp.choices[0].message.content.strip()
            txt = re.sub(r"^```json|```$", "", txt).strip()
            data = json.loads(txt)

            return (
                ValidationResult(nom, data["nom_corrige"],
                                float(data["confidence_nom"]), "gpt4"),
                ValidationResult(prenom, data["prenom_corrige"],
                                float(data["confidence_prenom"]), "gpt4"),
            )
        except Exception as e:
            logger.error("Name LLM error (%s %s): %s", nom, prenom, e, exc_info=False)
            return (
                ValidationResult(nom, nom, 0.0, "error"),
                ValidationResult(prenom, prenom, 0.0, "error"),
            )
