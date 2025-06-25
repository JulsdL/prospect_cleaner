import json, re, difflib, math
from typing import Tuple
from openai import AsyncOpenAI
from prospect_cleaner.models.validation_result import ValidationResult
from prospect_cleaner.settings import settings
from prospect_cleaner.logconf import logger

class NameValidator:
    """Isolated service ─ can be mocked in tests."""

    _prompt_tmpl = """
Analyse et corrige si nécessaire ces informations de nom/prénom, en utilisant l'email comme indice si disponible:
Nom: "{nom}"
Prénom: "{prenom}"
Email: "{email}"

Problèmes possibles à corriger :
        - Inversion nom/prénom (ex: "Dupont Pierre" → Prénom: "Pierre", Nom: "Dupont").
        - Noms composés mal séparés.
        - Noms multiculturels (européens, arabes, est-asiatiques, indiens, etc.).
        - Noms composés de type « nom de mariage + nom de jeune-fille » (ex : « Sophie Riben Bascher » → Prénom : « Sophie », Nom : « Riben Bascher »).

Instructions spécifiques pour noms multiculturels :
        - Noms Arabes : Les particules comme "Al-", "El-", "Ben", "Bin", "Bint", "Abu" font généralement partie du nom de famille. Ex: "Fatima Al-Mahmoud" → Prénom: "Fatima", Nom: "Al-Mahmoud". "Mohammed Ben Ali" → Prénom: "Mohammed", Nom: "Ben Ali".
        - Noms Est-Asiatiques (chinois, japonais, coréen, vietnamien) :
            - L'ordre peut être Nom puis Prénom (ex: "Zhang Li Wei" → Nom: "Zhang", Prénom: "Li Wei"). Sois attentif à l'ordre fourni et corrige seulement si manifestement inversé pour un contexte occidental.
            - Les prénoms peuvent être composés de plusieurs parties (ex: "Li Wei", "Xiao Li", "Kenjiro"). Ces parties doivent rester groupées dans le champ prénom. Ex: Prénom: "Xiao Li", Nom: "Chen" (si l'entrée était "Chen Xiao Li").
        - Noms Hispaniques/Portugais : Souvent composés de plusieurs noms et prénoms. Ex: "Maria João Da Silva Santos" → Prénom: "Maria João", Nom: "Da Silva Santos". Il est fréquent d'avoir un prénom composé et deux noms de famille. Si une partie du prénom semble être un nom de famille, il faut envisager de la déplacer. **Utilise l'email pour confirmer l'ordre et la composition des noms.**

Exemple de cas complexe :
Input: Nom: "Ben Ali Hassan", Prénom: "Mohammed", Email: "mohammed.benali@example.com"
Output attendu (si "Ben Ali Hassan" est le nom complet):
{{
    "nom_corrige": "Ben Ali Hassan",
    "prenom_corrige": "Mohammed",
    "confidence_nom": 0.85,
    "confidence_prenom": 0.95,
    "reasoning": "Nom de structure arabe, 'Ben' fait partie du nom de famille. Prénom simple. Email confirme la structure.",
    "corrections_appliquees": "Aucune correction, ordre initial correct."
}}

Input: Nom: "Tanaka", Prénom: "Hiroshi Kenji", Email: "h.tanaka@example.jp"
Output attendu:
{{
    "nom_corrige": "Tanaka",
    "prenom_corrige": "Hiroshi Kenji",
    "confidence_nom": 0.95,
    "confidence_prenom": 0.90,
    "reasoning": "Prénom japonais potentiellement composé (Hiroshi Kenji). Nom simple. Email ne contredit pas.",
    "corrections_appliquees": "Fusion des prénoms si jugé comme un prénom composé."
}}

Input: Nom: "Silva", Prénom: "Ana Beatriz Ferreira", Email: "ana.silva@lemoncurve.com"
Output attendu:
{{
    "nom_corrige": "Silva Ferreira",
    "prenom_corrige": "Ana Beatriz",
    "confidence_nom": 0.90,
    "confidence_prenom": 0.90,
    "reasoning": "Nom portugais. L'email 'ana.silva@lemoncurve.com' suggère fortement que 'Silva' est le premier nom de famille et 'Ana' ou 'Ana Beatriz' est le prénom. 'Ferreira' est donc probablement le deuxième nom de famille. La structure Prénom + Nom1 + Nom2 est courante. L'email est un indice fort pour 'Silva' comme nom principal et 'Ferreira' comme nom additionnel.",
    "corrections_appliquees": "Déplacement de 'Ferreira' du prénom vers le nom pour former 'Silva Ferreira', en s'appuyant sur l'indice de l'email."
}}

        Pour le score de confiance, évalue entre 0 et 1 sur ces critères :
        - Cohérence culturelle (les noms correspondent à une même origine et structure)
        - Probabilité que la séparation soit correcte
        - Complexité du cas (noms composés = moins de confiance)
        - Certitude de la correction appliquée

        Réponds uniquement en JSON :
        {{
            "nom_corrige": "nom corrigé",
            "prenom_corrige": "prénom corrigé",
            "confidence_nom": 0.95,
            "confidence_prenom": 0.90,
            "reasoning": "justification du score de confiance",
            "corrections_appliquees": "description des corrections"
        }}
"""
    # ------------------------------------------------------------------ #
    # Confidence helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Rapport de similarité (0-1) entre chaînes, simple et rapide."""
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

    @staticmethod
    def _calibrate(base: float, original: str, cleaned: str) -> float:
        """
        Ajuste la confiance :
        • si la correction est minime → score ↑
        • si elle est lourde → score ↓
        """
        sim = NameValidator._similarity(original, cleaned)
        # ex : inversion «Pierre | Dupont» → sim ~0.8
        #      reprise complète  → sim <0.5
        penalty = (1 - sim) * 0.4
        bonus   = sim * 0.2
        raw = min(max(base + bonus - penalty, 0), 1)
        # arrondi à l’entier supérieur sur deux décimales
        return math.ceil(raw * 100) / 100

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key)
            if settings.openai_api_key else None
        )

    async def validate(
        self, nom: str, prenom: str, email: str | None = None
    ) -> Tuple[ValidationResult, ValidationResult, str]: # Added str for explanation
        nom, prenom = (nom or "").strip(), (prenom or "").strip()
        email_str = (email or "").strip()
        name_explication = "" # Default empty explanation

        if not self._client or not (nom or prenom): # Email is optional for validation to proceed
            name_explication = "No LLM client or empty name/prenom input."
            return (
                ValidationResult(nom, nom, 0.0, "no_llm"),
                ValidationResult(prenom, prenom, 0.0, "no_llm"),
                name_explication,
            )

        prompt = self._prompt_tmpl.format(nom=nom, prenom=prenom, email=email_str)
        try:
            resp = await self._client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300, # Increased max_tokens slightly for potentially longer explanations
            )
            txt = resp.choices[0].message.content.strip()
            # Attempt to strip markdown and then load JSON
            # Handle cases where ```json might be missing or text isn't perfect JSON
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", txt, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # If no markdown block, assume the whole text is the JSON content
                # This might fail if the LLM includes non-JSON text without markdown
                json_str = txt

            data = json.loads(json_str)

            conf_nom     = self._calibrate(float(data.get("confidence_nom", 0.0)), nom, data.get("nom_corrige", nom))
            conf_prenom  = self._calibrate(float(data.get("confidence_prenom", 0.0)), prenom, data.get("prenom_corrige", prenom))

            reasoning = data.get("reasoning", "")
            corrections = data.get("corrections_appliquees", "")

            if reasoning and corrections:
                name_explication = f"Raisonnement: {reasoning}. Corrections: {corrections}."
            elif reasoning:
                name_explication = f"Raisonnement: {reasoning}."
            elif corrections:
                name_explication = f"Corrections: {corrections}."
            else:
                name_explication = "Aucune explication détaillée fournie par l'IA."

            # Ensure nom_corrige and prenom_corrige exist, otherwise use original
            nom_corrige = data.get("nom_corrige", nom)
            prenom_corrige = data.get("prenom_corrige", prenom)

            return (
                ValidationResult(nom, nom_corrige, conf_nom, "gpt4.1-mini"),
                ValidationResult(prenom, prenom_corrige, conf_prenom, "gpt4.1-mini"),
                name_explication,
            )

        except Exception as e:
            logger.error("Name LLM error (%s %s): %s", nom, prenom, e, exc_info=True) # exc_info=True for more details
            name_explication = f"Erreur lors de la validation du nom: {str(e)}"
            return (
                ValidationResult(nom, nom, 0.0, "error"),
                ValidationResult(prenom, prenom, 0.0, "error"),
                name_explication,
            )
