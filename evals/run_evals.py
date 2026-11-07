import argparse
import json
import logging
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sequel.agent import AgentFailure, ask_detailed
from sequel.config import MODEL
from sequel.evaluation import execute_query, results_equal, says_unanswerable

EVALS_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVALS_DIR / "questions.json"
RESULTS_PATH = EVALS_DIR / "results.db"
FAILURE_TYPES = {
    "wrong_result",
    "sql_error",
    "invalid_json",
    "hit_iteration_cap",
    "answered_unanswerable",
    "none",
}

logger = logging.getLogger("sequel.evals")


def load_questions() -> list[dict[str, Any]]:
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or len(questions) != 30:
        raise ValueError("questions.json must contain exactly 30 questions.")
    seen: set[str] = set()
    for question in questions:
        required = {"id", "question", "gold_sql", "difficulty", "split"}
        if not isinstance(question, dict) or not required.issubset(question):
            raise ValueError(f"Every question must contain {sorted(required)}.")
        if question["id"] in seen:
            raise ValueError(f"Duplicate question id: {question['id']}")
        if question["split"] not in {"dev", "test"}:
            raise ValueError(f"Invalid split for {question['id']}.")
        if question["difficulty"] not in {"easy", "medium", "hard"}:
            raise ValueError(f"Invalid difficulty for {question['id']}.")
        unanswerable = question.get("expected_unanswerable", False)
        if unanswerable != (question["gold_sql"] is None):
            raise ValueError(
                f"Question {question['id']} must set a null gold_sql exactly "
                "when expected_unanswerable is true."
            )
        seen.add(question["id"])
    split_counts = {
        split: sum(question["split"] == split for question in questions)
        for split in ("dev", "test")
    }
    if split_counts != {"dev": 10, "test": 20}:
        raise ValueError(f"Expected 10 dev and 20 test questions, found {split_counts}.")
    if sum(question.get("expected_unanswerable", False) for question in questions) != 3:
        raise ValueError("The benchmark must contain exactly three unanswerable items.")
    return questions


def verify_gold_queries(
    questions: list[dict[str, Any]],
) -> dict[str, list[tuple[Any, ...]]]:
    gold_results: dict[str, list[tuple[Any, ...]]] = {}
    for question in questions:
        if question.get("expected_unanswerable"):
            continue
        rows = execute_query(question["gold_sql"])
        if not rows:
            raise ValueError(f"Gold query for {question['id']} returned no rows.")
        gold_results[question["id"]] = rows
    return gold_results


def initialize_results_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            split TEXT NOT NULL CHECK (split IN ('dev', 'test', 'all')),
            started_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results (
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            question_id TEXT NOT NULL,
            difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
            correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
            failure_type TEXT NOT NULL CHECK (
                failure_type IN (
                    'wrong_result', 'sql_error', 'invalid_json',
                    'hit_iteration_cap', 'answered_unanswerable', 'none'
                )
            ),
            agent_sql TEXT NOT NULL,
            steps INTEGER NOT NULL,
            latency REAL NOT NULL,
            answer TEXT NOT NULL,
            error TEXT,
            PRIMARY KEY (run_id, question_id)
        );
        """
    )
    connection.commit()


def evaluate_question(
    question: dict[str, Any],
    gold_rows: list[tuple[Any, ...]] | None,
    model: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    answer = ""
    agent_sql = ""
    steps = 0
    error: str | None = None

    try:
        response = ask_detailed(question["question"], model=model)
        answer = response.answer
        agent_sql = response.sql
        steps = response.steps
    except AgentFailure as exc:
        steps = exc.steps
        error = str(exc)
        return {
            "correct": False,
            "failure_type": exc.failure_type,
            "agent_sql": agent_sql,
            "steps": steps,
            "latency": time.perf_counter() - started,
            "answer": answer,
            "error": error,
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return {
            "correct": False,
            "failure_type": "sql_error",
            "agent_sql": agent_sql,
            "steps": steps,
            "latency": time.perf_counter() - started,
            "answer": answer,
            "error": error,
        }

    expected_unanswerable = question.get("expected_unanswerable", False)
    if expected_unanswerable:
        correct = says_unanswerable(answer)
        failure_type = "none" if correct else "wrong_result"
        if not correct:
            error = "Agent answered instead of identifying that the data cannot answer."
    elif says_unanswerable(answer):
        correct = False
        failure_type = "answered_unanswerable"
        error = "Agent said the data could not answer an answerable question."
    elif not agent_sql:
        correct = False
        failure_type = "sql_error"
        error = "Agent did not execute a successful SQL query."
    else:
        try:
            agent_rows = execute_query(agent_sql)
        except Exception as exc:
            correct = False
            failure_type = "sql_error"
            error = f"{type(exc).__name__}: {exc}"
        else:
            correct = results_equal(gold_rows or [], agent_rows, question["gold_sql"])
            failure_type = "none" if correct else "wrong_result"

    return {
        "correct": correct,
        "failure_type": failure_type,
        "agent_sql": agent_sql,
        "steps": steps,
        "latency": time.perf_counter() - started,
        "answer": answer,
        "error": error,
    }


def run(split: str, model: str, limit: int | None) -> str:
    questions = load_questions()
    gold_results = verify_gold_queries(questions)
    selected = [
        question
        for question in questions
        if split == "all" or question["split"] == split
    ]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be at least 1.")
        selected = selected[:limit]
    if not selected:
        raise ValueError("No questions selected.")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(RESULTS_PATH) as connection:
        initialize_results_db(connection)
        connection.execute(
            "INSERT INTO runs (run_id, model, split, started_at) VALUES (?, ?, ?, ?)",
            (run_id, model, split, started_at),
        )
        connection.commit()

        for index, question in enumerate(selected, start=1):
            outcome = evaluate_question(
                question, gold_results.get(question["id"]), model
            )
            if outcome["failure_type"] not in FAILURE_TYPES:
                raise ValueError(
                    f"Unexpected failure type: {outcome['failure_type']}"
                )
            connection.execute(
                """
                INSERT INTO results (
                    run_id, question_id, difficulty, correct, failure_type,
                    agent_sql, steps, latency, answer, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    question["id"],
                    question["difficulty"],
                    int(outcome["correct"]),
                    outcome["failure_type"],
                    outcome["agent_sql"],
                    outcome["steps"],
                    outcome["latency"],
                    outcome["answer"],
                    outcome["error"],
                ),
            )
            connection.commit()
            status = "correct" if outcome["correct"] else "incorrect"
            print(
                f"[{index}/{len(selected)}] {question['id']} {status} "
                f"failure={outcome['failure_type']} steps={outcome['steps']} "
                f"latency={outcome['latency']:.2f}s"
            )
            if outcome["error"]:
                print(f"    {outcome['error']}")

    print(f"\nRun ID: {run_id}")
    print(f"Saved results to: {RESULTS_PATH}")
    return run_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure Sequel execution accuracy on the text-to-SQL benchmark."
    )
    parser.add_argument("--split", choices=("dev", "test", "all"), default="all")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run(args.split, args.model, args.limit)
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
