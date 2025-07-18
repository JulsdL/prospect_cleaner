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
    def __init__(
        self,
        nom_col: str = settings.default_nom_col,
        prenom_col: str = settings.default_prenom_col,
        entreprise_col: str = settings.default_entreprise_col,
        email_col: str = settings.default_email_col,
    ) -> None:
        self.name_validator    = NameValidator()
        self.company_validator = CompanyValidator()
        self.sem = asyncio.Semaphore(settings.max_concurrency)
        self.nom_col = nom_col
        self.prenom_col = prenom_col
        self.entreprise_col = entreprise_col
        self.email_col = email_col

    async def _process_row(self, row_idx: int, row, df: pd.DataFrame) -> None:
        """
        One row = one task.  We guard the LLM calls with a semaphore.
        """
        async with self.sem:
            email = row.get(self.email_col, "")
            # Updated to receive three values from name_validator and pass email
            n_res, p_res, name_expl = await self.name_validator.validate(
                row[self.nom_col], row[self.prenom_col], email
            )

            if isinstance(email, str) and "@" in email:
                domain = email.split("@")[-1]
            else:
                domain = ""

            c_res = await self.company_validator.validate(
                row[self.entreprise_col], domain
            )

        # update dataframe in‑place
        df.at[row_idx, f"{self.nom_col}_valide"]          = n_res.validated
        df.at[row_idx, f"{self.prenom_col}_valide"]       = p_res.validated
        df.at[row_idx, f"{self.entreprise_col}_validee"]  = c_res.validated

        df.at[row_idx, "confiance_nom"]        = n_res.confidence
        df.at[row_idx, "confiance_prenom"]     = p_res.confidence
        df.at[row_idx, "confiance_entreprise"] = c_res.confidence
        df.at[row_idx, "entreprise_citations"] = c_res.source
        df.at[row_idx, "entreprise_explication"] = c_res.explanation
        df.at[row_idx, "name_explication"]     = name_expl # Added new column
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
        df = read_csv(input_path)

        # ensure all result columns are present
        result_cols = {
            f"{self.nom_col}_valide":        "",
            f"{self.prenom_col}_valide":     "",
            f"{self.entreprise_col}_validee": "",
            "confiance_nom":         0.0,
            "confiance_prenom":      0.0,
            "confiance_entreprise":  0.0,
            "entreprise_citations":  "",
            "entreprise_explication":"",
            "name_explication":      "", # Added new column default
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

        # 🚀 Affiche le résumé en console
        self._print_summary(df)


    def _print_summary(self, df: pd.DataFrame) -> None:
        """Affiche un résumé des traitements en console."""
        total = len(df)
        processed = df[df["source_validation"] != ""]
        cnt = len(processed)

        if cnt == 0:
            print("\n=== AUCUNE LIGNE TRAITÉE ===")
            return

        # Corrections appliquées
        nom_corr = (processed[self.nom_col] != processed[f"{self.nom_col}_valide"]).sum()
        prenom_corr = (processed[self.prenom_col] != processed[f"{self.prenom_col}_valide"]).sum()
        ent_corr = (processed[self.entreprise_col] != processed[f"{self.entreprise_col}_validee"]).sum()

        # Moyennes de confiance
        avg_nom = processed["confiance_nom"].mean()
        avg_prenom = processed["confiance_prenom"].mean()
        avg_ent = processed["confiance_entreprise"].mean()

        print("\n=== RÉSUMÉ DU TRAITEMENT ===")
        print(f"Total lignes dans le fichier: {total}")
        print(f"Lignes traitées: {cnt}")
        print(f"Corrections noms: {nom_corr} ({nom_corr/cnt*100:.1f}%)")
        print(f"Corrections prénoms: {prenom_corr} ({prenom_corr/cnt*100:.1f}%)")
        print(f"Corrections entreprises: {ent_corr} ({ent_corr/cnt*100:.1f}%)")
        print(f"Confiance moyenne - Noms: {avg_nom:.2f}")
        print(f"Confiance moyenne - Prénoms: {avg_prenom:.2f}")
        print(f"Confiance moyenne - Entreprises: {avg_ent:.2f}")

        # Exemples
        print("\n=== EXEMPLES DE CORRECTIONS ===")

        # Noms
        ex_noms = processed[processed[self.nom_col] != processed[f"{self.nom_col}_valide"]].head(3)
        if not ex_noms.empty:
            print("\nCorrections de noms:")
            for _, row in ex_noms.iterrows():
                print(f"  {row[self.nom_col]} → {row[f'{self.nom_col}_valide']} (confiance: {row['confiance_nom']:.2f})")

        # Entreprises
        ex_ent = processed[processed[self.entreprise_col] != processed[f"{self.entreprise_col}_validee"]].head(3)
        if not ex_ent.empty:
            print("\nCorrections d'entreprises:")
            for _, row in ex_ent.iterrows():
                print(f"  {row[self.entreprise_col]} → {row[f'{self.entreprise_col}_validee']} (confiance: {row['confiance_entreprise']:.2f})")
