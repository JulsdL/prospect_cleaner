from fastapi import FastAPI
from pydantic import BaseModel
from prospect_cleaner.services.prospect_cleaner import ProspectDataCleaner
from prospect_cleaner.logconf import logger
import asyncio
from pathlib import Path

app = FastAPI()

from typing import Optional

class CleanRequest(BaseModel):
    input_path: str
    output_path: str
    nom_col: Optional[str] = None
    prenom_col: Optional[str] = None
    entreprise_col: Optional[str] = None
    email_col: Optional[str] = None

@app.post("/clean_prospects/")
async def clean_prospects_endpoint(request: CleanRequest):
    cleaner_args = {}
    if request.nom_col:
        cleaner_args["nom_col"] = request.nom_col
    if request.prenom_col:
        cleaner_args["prenom_col"] = request.prenom_col
    if request.entreprise_col:
        cleaner_args["entreprise_col"] = request.entreprise_col
    if request.email_col:
        cleaner_args["email_col"] = request.email_col

    cleaner = ProspectDataCleaner(**cleaner_args)
    try:
        # Ensure paths are valid Path objects
        input_p = Path(request.input_path)
        output_p = Path(request.output_path)

        # Ensure the output directory exists
        output_p.parent.mkdir(parents=True, exist_ok=True)

        await cleaner.clean(input_p, output_p)
        return {"message": f"Prospect cleaning started. Input: {request.input_path}, Output: {request.output_path}"}
    except FileNotFoundError:
        logger.error(f"Input file not found: {request.input_path}")
        return {"error": f"Input file not found: {request.input_path}"}
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return {"error": f"An error occurred: {str(e)}"}

@app.get("/")
async def root():
    return {"message": "Prospect Cleaner API is running."}
