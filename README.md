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

## Results

Held-out test results (one run per model):

| Model | Overall | Easy | Medium | Hard | Questions | Avg. steps | Avg. latency | Failure types |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| qwen2.5-coder:7b | 65.0% | 100.0% | 44.4% | 66.7% | 20 | 3.35 | 9.74s | wrong_result=6, answered_unanswerable=1, none=13 |
| llama3 | 40.0% | 100.0% | 22.2% | 16.7% | 20 | 4.15 | 13.20s | wrong_result=8, invalid_json=2, answered_unanswerable=2, none=8 |
| mistral | 5.0% | 0.0% | 11.1% | 0.0% | 20 | 6.80 | 42.12s | wrong_result=5, sql_error=2, hit_iteration_cap=11, answered_unanswerable=1, none=1 |

Benchmark caveat: Q027's gold SQL joins the top-ranked job to `stg_jobs`, where
that job ID has four rows, so the gold result repeats the same posting four
times. The query was left unchanged; its reported score is execution accuracy
against the supplied gold SQL.

Development-split results were used for prompt tuning and are not reported as
accuracy; only the held-out test results above are reported.

Limitations:

- 20 test questions; one question is 5 percentage points.
- Results cover a single dataset.
- Gold queries were written by an LLM.
- Each model was run once, so run-to-run variance is not measured.
