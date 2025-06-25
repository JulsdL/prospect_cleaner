import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()  # load .env

class _Settings(BaseSettings):
    # OpenAI
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # CSV defaults
    # Default column names, can be overridden at runtime
    default_nom_col: str        = "nom"
    default_prenom_col: str     = "prenom"
    default_entreprise_col: str = "raison_sociale"
    default_email_col: str      = "email"

    # Runtime
    batch_size: int = 10          # rows per save
    max_concurrency: int = 5      # parallel tasks

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = _Settings()           # singleton
