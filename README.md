# Sequel

Sequel is a local text-to-SQL analyst. It uses Ollama for the model and a
read-only DuckDB copy of the `analytics` tables in the local `signal` Postgres
database.

## Setup

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` to the password for
   the local `postgres` user. `SEQUEL_MODEL` and `OLLAMA_BASE_URL` have defaults.
3. Build the local database and generate documentation from the live schema and
   sample rows:

   ```powershell
   python build_db.py
   ```

4. Ask a question:

   ```powershell
   python ask.py "Which skills are growing fastest?"
   ```

The agent can run only a single read-only `SELECT`/`WITH ... SELECT` per query,
returns at most 50 rows, and interrupts queries after five seconds.
