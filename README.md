# Prospect Cleaner

Prospect Cleaner is a tool designed to clean and validate prospect data from CSV files. It utilizes Large Language Models (LLMs) to validate and potentially correct names and company information, providing confidence scores and explanations for its actions. It can be run as a command-line tool or as a FastAPI web service.

## Table of Contents

*   [Features](#features)
*   [Prerequisites](#prerequisites)
*   [Configuration](#configuration)
*   [Installation](#installation)
*   [Usage](#usage)
    *   [Docker](#docker)
    *   [Command-Line Interface (CLI)](#command-line-interface-cli)
    *   [API (Directly)](#api-directly)
*   [Input/Output CSV Format](#inputoutput-csv-format)
*   [Development](#development)
*   [Contributing](#contributing)
*   [License](#license)

## Features

*   **CSV Data Cleaning**: Processes input CSV files containing prospect data.
*   **LLM-Powered Validation**:
    *   Validates and suggests corrections for first names and last names.
    *   Validates and suggests corrections for company names.
*   **Detailed Output**: Generates an output CSV with:
    *   Validated data.
    *   Confidence scores for each validation.
    *   Explanations and sources for validation decisions.
*   **Multiple Interfaces**:
    *   Exposes functionality via a FastAPI HTTP API.
    *   Provides a command-line interface (CLI) for direct execution.
*   **Dockerized**: Includes a `Dockerfile` for easy containerization and deployment.
*   **Asynchronous Processing**: Efficiently handles multiple rows in the CSV using asynchronous operations.

## Prerequisites

*   **Python**: Python 3.12 or higher.
*   **Docker**: Required if you plan to run the application using Docker. (See [Docker installation guide](https://docs.docker.com/engine/install/))
*   **OpenAI API Key**: You need an API key from OpenAI to use the LLM-based validation features. This key should be set as an environment variable in an `.env` file.

## Configuration

The application uses an `.env` file to manage environment variables. Create an `.env` file in the root of the project.

Example `.env` file content:
```env
OPENAI_API_KEY="your_openai_api_key_here"

# Optional: CSV column names (defaults are shown)
# NOM_COL="nom"
# PRENOM_COL="prenom"
# ENTREPRISE_COL="raison_sociale"
# EMAIL_COL="email"

# Optional: Runtime settings (defaults are shown)
# BATCH_SIZE=10
# MAX_CONCURRENCY=5
```

**Key Environment Variables:**

*   `OPENAI_API_KEY` (Required): Your API key for OpenAI services.
*   `NOM_COL`: The name of the column in your input CSV that contains the last name. Defaults to `nom`.
*   `PRENOM_COL`: The name of the column for the first name. Defaults to `prenom`.
*   `ENTREPRISE_COL`: The name of the column for the company name. Defaults to `raison_sociale`.
*   `EMAIL_COL`: The name of the column for the email address (used to extract domain for company validation). Defaults to `email`.
*   `BATCH_SIZE`: The number of rows to process before saving the output CSV. Defaults to `10`.
*   `MAX_CONCURRENCY`: The maximum number of concurrent tasks for processing rows. Defaults to `5`.

These settings are defined in `prospect_cleaner/settings.py` and can be overridden by setting the corresponding environment variables in your `.env` file.

## Installation

Follow these steps to set up the project for local development or direct CLI usage (i.e., not using Docker). If you only plan to use Docker, you can skip to the [Docker usage](#docker) section.

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>  # Replace <repository_url> with the actual URL
    cd prospect-cleaner
    ```

2.  **Create a virtual environment:**
    It's recommended to use a virtual environment to manage project dependencies.
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up environment variables:**
    Create an `.env` file in the project root as described in the [Configuration](#configuration) section. At a minimum, it should contain your `OPENAI_API_KEY`.
    ```env
    OPENAI_API_KEY="your_openai_api_key_here"
    ```

## Usage

This section outlines how to get started with Prospect Cleaner using Docker, the Command-Line Interface (CLI), or by directly running the API.

### Docker

Using Docker is the recommended way to run Prospect Cleaner, especially for deployment or to ensure a consistent environment.

1.  **Build the Docker image:**
    Ensure you have Docker installed and running. Navigate to the project's root directory (where the `Dockerfile` is located) and run:
    ```bash
    DOCKER_BUILDKIT=1 docker build -t prospect-cleaner-api .
    ```

2.  **Prepare your data and `.env` file:**
    *   Create an `.env` file in your current working directory (e.g., the project root) with your `OPENAI_API_KEY` and any other configurations you wish to override.
    *   Ensure your input CSV file (e.g., `test_input.csv`) is accessible. For Docker, you'll typically place it in a directory that you can mount as a volume (e.g., a `data` directory in your project root).

3.  **Run the Docker container:**
    The following command runs the container, exposes the API on port 8000, mounts a local `./data` directory to `/app/data` inside the container, and loads environment variables from your local `.env` file.
    ```bash
    docker run --rm \
      --env-file .env \
      -v "$(pwd)/data:/app/data:rw" \
      -p 8000:8000 \
      prospect-cleaner-api
    ```
    *   `--rm`: Automatically removes the container when it exits.
    *   `--env-file .env`: Loads environment variables from the `.env` file located in your host's current directory when you run the command.
    *   `-v "$(pwd)/data:/app/data:rw"`: Mounts the `data` directory from your host's current path (`$(pwd)/data`) to `/app/data` in the container with read-write permissions. Adjust `$(pwd)/data` if your data directory is located elsewhere on your host.
    *   `-p 8000:8000`: Maps port 8000 on your host to port 8000 in the container.
    *   `prospect-cleaner-api`: The name of the image you built.

4.  **Accessing the API via Docker:**
    Once the container is running, the API will be accessible at `http://localhost:8000`.
    *   Root endpoint: `GET http://localhost:8000/`
    *   Interactive API docs: `http://localhost:8000/docs`
    *   Clean prospects endpoint: `POST http://localhost:8000/clean_prospects/`

    Example using `curl` to process `data/test_input.csv` and save to `data/test_output.csv` (paths are relative to `/app` inside the container):
    ```bash
    curl -X POST "http://localhost:8000/clean_prospects/" \
         -H "Content-Type: application/json" \
         -d '{
               "input_path": "data/test_input.csv",
               "output_path": "data/test_output.csv"
             }'
    ```
    **Note**: The `input_path` and `output_path` in the JSON payload should be paths accessible *inside* the container (e.g., `data/my_prospects.csv` if you mounted your local `./data` directory to `/app/data`).

### Command-Line Interface (CLI)

Run the prospect cleaning process directly from the command line after completing the [Installation](#installation) steps (virtual environment activated, dependencies installed, `.env` file present).

1.  **Ensure your `.env` file is present** in the project root with at least `OPENAI_API_KEY`.

2.  **Run the script:**
    The script `prospect_cleaner/cli/clean_prospects.py` handles the cleaning.
    ```bash
    python -m prospect_cleaner.cli.clean_prospects -i path/to/your/input.csv -o path/to/your/output.csv
    ```
    *   `-i, --input`: Path to the input CSV file. Defaults to `data/prospects_input.csv`.
    *   `-o, --output`: Path to the output CSV file. Defaults to `data/prospects_cleaned.csv`.

    Example using default paths (creates `data/prospects_cleaned.csv` from `data/prospects_input.csv`):
    ```bash
    python -m prospect_cleaner.cli.clean_prospects
    ```

    Example with custom paths:
    ```bash
    python -m prospect_cleaner.cli.clean_prospects --input my_inputs.csv --output my_outputs.csv
    ```

### API (Directly)

If you have followed the [Installation](#installation) steps, you can run the FastAPI application directly. This is useful for development or if you prefer not to use Docker.

1.  **Ensure your `.env` file is present** in the project root.
2.  **Start the FastAPI server using Uvicorn:**
    From the project root directory:
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```
    *   `--reload`: Enables auto-reloading on code changes (for development).
    *   `--host 0.0.0.0`: Makes the server accessible from your network.
    *   `--port 8000`: Runs on port 8000.

3.  **Access the API:**
    *   Root: `GET http://localhost:8000/`
    *   Interactive Docs (Swagger UI): `http://localhost:8000/docs`
    *   Alternative Docs (ReDoc): `http://localhost:8000/redoc`
    *   Clean Prospects Endpoint: `POST http://localhost:8000/clean_prospects/`

    Use tools like `curl`, Postman, or the interactive docs to send requests. The `input_path` and `output_path` for the `/clean_prospects/` endpoint should be valid paths accessible by the server process.

## Input/Output CSV Format

### Input CSV

The input CSV file must contain columns for prospect information. By default, the application expects (configurable via environment variables, see [Configuration](#configuration)):

*   `nom`: Last name.
*   `prenom`: First name.
*   `raison_sociale`: Company name.
*   `email`: Email address (domain used for company validation hint).

Example `input.csv`:
```csv
nom,prenom,raison_sociale,email
Doe,John,Example Corp,j.doe@example.com
Smith,Jane,Acme Inc,jane.smith@acme.com
```

### Output CSV

The output CSV includes all original columns plus:

*   `{nom_col}_valide`: Validated/corrected last name (e.g., `nom_valide`).
*   `{prenom_col}_valide`: Validated/corrected first name (e.g., `prenom_valide`).
*   `{entreprise_col}_validee`: Validated/corrected company name (e.g., `raison_sociale_validee`).
*   `confiance_nom`: Confidence score (0.0-1.0) for last name validation.
*   `confiance_prenom`: Confidence score (0.0-1.0) for first name validation.
*   `confiance_entreprise`: Confidence score (0.0-1.0) for company validation.
*   `entreprise_citations`: Source/citation for company validation.
*   `entreprise_explication`: Explanation for company validation.
*   `name_explication`: Explanation for name validation.
*   `source_validation`: Consolidated validation source/status (e.g., `nom:LLM_MATCH`).

The exact names of `_valide`/`_validee` columns depend on input column configuration.

## Development

To contribute to Prospect Cleaner:

1.  **Local Setup:** Follow [Installation](#installation) to clone, set up a virtual environment, and install dependencies.
2.  **Run API Locally:** Use Uvicorn as in [API (Directly)](#api-directly) for the FastAPI server with auto-reload:
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```
3.  **Run CLI:** Execute as per [Command-Line Interface (CLI)](#command-line-interface-cli).
4.  **Code Style & Linting**: (Details on linters like Flake8/Black would go here if set up).
5.  **Tests**: (Instructions for running automated tests. No specific suite identified yet).

Ensure an `.env` file with `OPENAI_API_KEY` is present for development.

## Contributing

Contributions are welcome! Please:

1.  Fork the repository.
2.  Create a branch (`git checkout -b feature/your-feature` or `bugfix/your-fix`).
3.  Commit changes with clear messages.
4.  Push to your fork.
5.  Open a pull request.

Adhere to style guidelines and add tests if applicable.

## License

This project is not currently licensed. It is recommended to add a `LICENSE` file (e.g., MIT, Apache 2.0, GPL) to define usage and contribution terms.
