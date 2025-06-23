from fastapi import FastAPI
from pydantic import BaseModel
from prospect_cleaner.services.prospect_cleaner import ProspectDataCleaner
from prospect_cleaner.logconf import logger
import asyncio
from pathlib import Path

app = FastAPI()

class CleanRequest(BaseModel):
    input_path: str
    output_path: str

@app.post("/clean_prospects/")
async def clean_prospects_endpoint(request: CleanRequest):
    cleaner = ProspectDataCleaner()
    try:
        # Ensure paths are valid Path objects
        input_p = Path(request.input_path)
        output_p = Path(request.output_path)

        # It's good practice to ensure the output directory exists
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
