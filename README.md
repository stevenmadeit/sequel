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

## Execution-accuracy evaluations

The benchmark in `evals/questions.json` has 10 development questions and 20
held-out test questions, spanning easy, medium, and hard cases. Run it with:

```powershell
python evals/run_evals.py --split dev
python evals/run_evals.py --split test --model qwen2.5-coder:7b
python evals/run_evals.py --split all --limit 5
python evals/compare.py
```

Each run compares the rows returned by the agent's SQL with the corresponding
gold SQL using execution accuracy. Run metadata and per-question outcomes are
stored in the local, git-ignored `evals/results.db`. The comparison report
includes accuracy by difficulty, average steps and latency, and failure types.

Use the **dev** split when tuning the system prompt. Keep the **test** split
only for final reporting: repeatedly tuning against reported test questions
can overfit the prompt to those examples and make the measured accuracy look
better than performance on unseen questions.
