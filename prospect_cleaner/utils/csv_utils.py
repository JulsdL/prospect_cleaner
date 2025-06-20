import pandas as pd
from pathlib import Path
from .async_utils import run_sync
from prospect_cleaner.logconf import logger

def read_csv(path: str | Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8", skipinitialspace=True).dropna(axis=1, how="all")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin-1", skipinitialspace=True).dropna(axis=1, how="all")
    except Exception as exc:
        logger.error("CSV read failed: %s", exc, exc_info=False)
        raise

@run_sync
def write_csv(df, path: str | Path) -> None:
    """
    Write DataFrame to CSV on a thread pool so it doesn't block the event loop.
    """
    df.to_csv(path, index=False)
