"""
Orchestrates the validators and CSV IO.
Supports parallel rows processing with asyncio.gather.
"""

from __future__ import annotations

import asyncio, time
from pathlib import Path
import pandas as pd
from prospect_cleaner.settings import settings
from prospect_cleaner.logconf import logger
from prospect_cleaner.services.name_validator import NameValidator
from prospect_cleaner.services.company_validator import CompanyValidator
from prospect_cleaner.utils.csv_utils import read_csv, write_csv

class ProspectDataCleaner:
    def __init__(self) -> None:
        self.name_validator    = NameValidator()
        self.company_validator = CompanyValidator()
        self.sem = asyncio.Semaphore(settings.max_concurrency)

    async def _process_row(self, row_idx: int, row, df: pd.DataFrame) -> None:
        """
        One row = one task.  We guard the LLM calls with a semaphore.
        """
        async with self.sem:
            n_res, p_res = await self.name_validator.validate(
                row[settings.nom_col], row[settings.prenom_col]
            )

            email = row.get(settings.email_col, "")
            if isinstance(email, str) and "@" in email:
                domain = email.split("@")[-1]
            else:
                domain = ""

            c_res = await self.company_validator.validate(
                row[settings.entreprise_col], domain
            )

        # update dataframe in‑place
        df.at[row_idx, f"{settings.nom_col}_valide"]          = n_res.validated
        df.at[row_idx, f"{settings.prenom_col}_valide"]       = p_res.validated
        df.at[row_idx, f"{settings.entreprise_col}_validee"]  = c_res.validated

        df.at[row_idx, "confiance_nom"]        = n_res.confidence
        df.at[row_idx, "confiance_prenom"]     = p_res.confidence
        df.at[row_idx, "confiance_entreprise"] = c_res.confidence
        df.at[row_idx, "entreprise_citations"] = c_res.source
        df.at[row_idx, "entreprise_explication"] = c_res.explanation
        df.at[row_idx, "source_validation"]    = f"nom:{n_res.source}"

    async def _save_loop(self, df: pd.DataFrame, out: Path) -> None:
        """
        Every `batch_size` rows or 10 s (whichever first) we save to disk.
        """
        last_save, processed = time.time(), 0
        while True:
            await asyncio.sleep(1)
            new_processed = (df["source_validation"] != "").sum()
            if new_processed - processed >= settings.batch_size or time.time() - last_save > 10:
                await write_csv(df, out)
                processed, last_save = new_processed, time.time()
            if new_processed == len(df):
                await write_csv(df, out)   # final flush
                return

    async def clean(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> None:
        # df = read_csv(input_path)
        # for col in ("_valide", "_validee",
        #             "confiance_nom", "confiance_prenom", "confiance_entreprise",
        #             "source_validation"):
        #     if col not in df.columns:
        #         df[col] = ""

        df = read_csv(input_path)

        # ensure all result columns are present
        result_cols = {
            f"{settings.nom_col}_valide":        "",
            f"{settings.prenom_col}_valide":     "",
            f"{settings.entreprise_col}_validee": "",
            "confiance_nom":         0.0,
            "confiance_prenom":      0.0,
            "confiance_entreprise":  0.0,
            "entreprise_citations":  "",
            "entreprise_explication":"",
            "source_validation":     "",
        }
        for col, default in result_cols.items():
            if col not in df.columns:
                df[col] = default

        tasks = [
            self._process_row(idx, df.iloc[idx].copy(), df)
            for idx in df.index
        ]

        saver = asyncio.create_task(self._save_loop(df, output_path))
        await asyncio.gather(*tasks)
        await saver
        logger.info("Cleaning finished (%s → %s)", input_path, output_path)
