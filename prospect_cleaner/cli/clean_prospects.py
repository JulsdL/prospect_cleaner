import asyncio, argparse, sys
from pathlib import Path
from prospect_cleaner.services.prospect_cleaner import ProspectDataCleaner
from prospect_cleaner.logconf import logger

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Clean a prospect CSV using LLM validation."
    )
    parser.add_argument("-i", "--input", default="data/prospects_input_small.csv")
    parser.add_argument("-o", "--output", default="data/prospects_cleaned.csv")
    args = parser.parse_args(argv)

    cleaner = ProspectDataCleaner()
    try:
        asyncio.run(cleaner.clean(Path(args.input), Path(args.output)))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")

if __name__ == "__main__":
    main(sys.argv[1:])
