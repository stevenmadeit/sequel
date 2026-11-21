import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sequel.agent import AgentFailure, AgentResponse, ask_detailed
from sequel.config import MODEL
from sequel.evaluation import says_unanswerable

OUTPUT_DIR = ROOT / "frontend" / "public" / "demo"
EVALS_DB = ROOT / "evals" / "results.db"
QUESTIONS_FILE = ROOT / "evals" / "questions.json"
SCHEMA_FILE = ROOT / "schema_docs.md"

DEMO_QUESTIONS = [
    {
        "id": "post-count",
        "difficulty": "easy",
        "question": "How many job postings are in the database?",
    },
    {
        "id": "company-count",
        "difficulty": "easy",
        "question": "How many distinct companies have job postings?",
    },
    {
        "id": "top-skills",
        "difficulty": "medium",
        "question": "Which skill is mentioned most often, and how many mentions does it have?",
    },
    {
        "id": "top-category",
        "difficulty": "medium",
        "question": "Which job category has the most job postings?",
    },
    {
        "id": "javascript-trend",
        "difficulty": "medium",
        "question": "Show daily job posting counts from August 25 through September 5, 2026.",
    },
    {
        "id": "cooccurring-skills",
        "difficulty": "hard",
        "question": "Which skills appear together in the most job postings? Include every tied pair.",
    },
    {
        "id": "monthly-counts-recovery",
        "difficulty": "hard",
        "question": "Count job postings by month. Use TO_CHAR(publication_date, 'YYYY-MM') as the month label.",
        "must_recover_sql_error": True,
    },
    {
        "id": "unanswerable-interviews",
        "difficulty": "hard",
        "question": "What is the average number of interview rounds by company?",
        "expected_unanswerable": True,
    },
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def record_traces() -> list[dict[str, Any]]:
    traces = []
    for index, item in enumerate(DEMO_QUESTIONS, start=1):
        events: list[dict[str, Any]] = []

        def capture(event_type: str, data: dict[str, Any]) -> None:
            events.append({"type": event_type, "data": data})

        try:
            response: AgentResponse = ask_detailed(
                item["question"],
                on_event=capture,
            )
            events.append(
                {
                    "type": "final",
                    "data": {
                        "answer": response.answer,
                        "sql": response.sql,
                        "steps": response.steps,
                    },
                }
            )
            answer = response.answer
            sql = response.sql
            steps = response.steps
        except AgentFailure as exc:
            events.append(
                {
                    "type": "error",
                    "data": {
                        "message": str(exc),
                        "failure_type": exc.failure_type,
                        "steps": exc.steps,
                    },
                }
            )
            answer = ""
            sql = ""
            steps = exc.steps
            if item.get("must_recover_sql_error"):
                raise RuntimeError(
                    f"{item['id']} did not finish; cannot record recovered SQL error."
                ) from exc

        sql_steps = {
            event["data"].get("step")
            for event in events
            if event["type"] == "action" and event["data"].get("tool") == "run_sql"
        }
        sql_results = [
            event["data"]
            for event in events
            if event["type"] == "result" and event["data"].get("step") in sql_steps
        ]
        has_recovered_sql_error = any(
            result.get("error") for result in sql_results
        ) and any(not result.get("error") for result in sql_results)
        if item.get("must_recover_sql_error") and not has_recovered_sql_error:
            raise RuntimeError(
                f"The real agent did not hit and recover from a SQL error for "
                f"{item['id']}. No hand-written trace was substituted."
            )
        if item.get("expected_unanswerable") and not says_unanswerable(answer):
            raise RuntimeError(
                f"The real agent did not identify {item['id']} as unanswerable."
            )

        traces.append(
            {
                **{
                    key: value
                    for key, value in item.items()
                    if key not in {"must_recover_sql_error"}
                },
                "model": MODEL,
                "events": events,
                "answer": answer,
                "sql": sql,
                "steps": steps,
            }
        )
        print(
            f"[{index}/{len(DEMO_QUESTIONS)}] {item['id']} "
            f"events={len(events)} steps={steps} "
            f"sql_error_recovered={has_recovered_sql_error}"
        )
    return traces


def export_evaluations() -> dict[str, Any]:
    if not EVALS_DB.exists():
        raise FileNotFoundError(f"Evaluation database is missing: {EVALS_DB}")
    if not QUESTIONS_FILE.exists():
        raise FileNotFoundError(f"Evaluation questions are missing: {QUESTIONS_FILE}")
    questions = {
        item["id"]: item
        for item in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    }

    connection = sqlite3.connect(EVALS_DB)
    connection.row_factory = sqlite3.Row
    try:
        runs = []
        results = []
        for run in connection.execute(
            "SELECT run_id, model, split, started_at FROM runs ORDER BY started_at DESC"
        ):
            run_rows = connection.execute(
                """
                SELECT question_id, difficulty, correct, failure_type, agent_sql,
                       steps, latency, answer, error
                FROM results WHERE run_id = ? ORDER BY question_id
                """,
                (run["run_id"],),
            ).fetchall()
            if not run_rows:
                continue
            total = len(run_rows)
            correct = sum(row["correct"] for row in run_rows)
            by_difficulty = {}
            for difficulty in ("easy", "medium", "hard"):
                subset = [row for row in run_rows if row["difficulty"] == difficulty]
                by_difficulty[difficulty] = {
                    "correct": sum(row["correct"] for row in subset),
                    "total": len(subset),
                    "accuracy": (
                        sum(row["correct"] for row in subset) / len(subset)
                        if subset
                        else 0
                    ),
                }
            failure_types: dict[str, int] = {}
            for row in run_rows:
                failure_types[row["failure_type"]] = (
                    failure_types.get(row["failure_type"], 0) + 1
                )
                question = questions.get(row["question_id"], {})
                results.append(
                    {
                        **dict(row),
                        "run_id": run["run_id"],
                        "question": question.get("question", row["question_id"]),
                        "gold_sql": question.get("gold_sql"),
                    }
                )
            runs.append(
                {
                    "run_id": run["run_id"],
                    "model": run["model"],
                    "split": run["split"],
                    "started_at": run["started_at"],
                    "total": total,
                    "correct": correct,
                    "accuracy": correct / total,
                    "accuracy_by_difficulty": by_difficulty,
                    "failure_types": failure_types,
                    "average_steps": sum(row["steps"] for row in run_rows) / total,
                    "average_latency": sum(row["latency"] for row in run_rows) / total,
                }
            )
        return {"runs": runs, "results": results}
    finally:
        connection.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    traces = record_traces()
    _write_json(
        OUTPUT_DIR / "traces.json",
        {"model": MODEL, "recorded_at": __import__("datetime").datetime.now().astimezone().isoformat(), "traces": traces},
    )
    _write_json(OUTPUT_DIR / "evals.json", export_evaluations())
    _write_json(
        OUTPUT_DIR / "schema.json",
        {"content": SCHEMA_FILE.read_text(encoding="utf-8")},
    )
    print(f"Recorded {len(traces)} traces and exported eval/schema snapshots to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
