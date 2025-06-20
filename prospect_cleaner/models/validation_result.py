from dataclasses import dataclass

@dataclass
class ValidationResult:
    original: str
    validated: str
    confidence: float
    source: str
    explanation: str = ""
