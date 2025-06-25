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
    parser.add_argument("--nom-col", help="Name of the last name column")
    parser.add_argument("--prenom-col", help="Name of the first name column")
    parser.add_argument("--entreprise-col", help="Name of the company column")
    parser.add_argument("--email-col", help="Name of the email column")
    args = parser.parse_args(argv)

    cleaner_args = {}
    if args.nom_col:
        cleaner_args["nom_col"] = args.nom_col
    if args.prenom_col:
        cleaner_args["prenom_col"] = args.prenom_col
    if args.entreprise_col:
        cleaner_args["entreprise_col"] = args.entreprise_col
    if args.email_col:
        cleaner_args["email_col"] = args.email_col

    cleaner = ProspectDataCleaner(**cleaner_args)
    try:
        asyncio.run(cleaner.clean(Path(args.input), Path(args.output)))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")

if __name__ == "__main__":
    main(sys.argv[1:])
