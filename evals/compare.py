import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

RESULTS_PATH = Path(__file__).resolve().parent / "results.db"
DIFFICULTIES = ("easy", "medium", "hard")
FAILURE_TYPES = (
    "wrong_result",
    "sql_error",
    "invalid_json",
    "hit_iteration_cap",
    "answered_unanswerable",
    "none",
)


def _percentage(correct: int, total: int) -> str:
    return f"{100 * correct / total:.1f}%" if total else "n/a"


def _load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No evaluation results found at {path}.")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT runs.run_id, runs.model, runs.split, runs.started_at,
                       results.question_id, results.difficulty, results.correct,
                       results.failure_type, results.steps, results.latency
                FROM runs
                JOIN results ON results.run_id = runs.run_id
                """
            )
        ]
    finally:
        connection.close()


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    output = [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
    ]
    output.extend(
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(output)


def main() -> int:
    try:
        results = _load_results(RESULTS_PATH)
    except Exception as exc:
        print(f"Could not load evaluation results: {exc}")
        return 1
    if not results:
        print(f"No evaluation results found in {RESULTS_PATH}.")
        return 0

    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_run[result["run_id"]].append(result)

    summaries = []
    for run_results in by_run.values():
        first = run_results[0]
        total = len(run_results)
        correct = sum(row["correct"] for row in run_results)
        by_difficulty = {}
        for difficulty in DIFFICULTIES:
            subset = [row for row in run_results if row["difficulty"] == difficulty]
            by_difficulty[difficulty] = _percentage(
                sum(row["correct"] for row in subset), len(subset)
            )
        failures = Counter(row["failure_type"] for row in run_results)
        summaries.append(
            {
                "model": first["model"],
                "split": first["split"],
                "started_at": first["started_at"],
                "question_count": total,
                "points_per_question": 100 / total,
                "accuracy": correct / total,
                "overall": _percentage(correct, total),
                "by_difficulty": by_difficulty,
                "avg_steps": sum(row["steps"] for row in run_results) / total,
                "avg_latency": sum(row["latency"] for row in run_results) / total,
                "failures": failures,
            }
        )
    summaries.sort(
        key=lambda summary: (
            -summary["accuracy"],
            summary["model"].casefold(),
            summary["split"],
            summary["started_at"],
        )
    )

    headers = [
        "Model",
        "Split",
        "Accuracy",
        "Easy",
        "Medium",
        "Hard",
        "Questions",
        "pp/question",
        "Avg steps",
        "Avg latency",
        "Failure types",
    ]
    rows = []
    for summary in summaries:
        failure_text = ", ".join(
            f"{kind}={summary['failures'].get(kind, 0)}"
            for kind in FAILURE_TYPES
            if summary["failures"].get(kind, 0)
        ) or "none"
        rows.append(
            [
                summary["model"],
                summary["split"],
                summary["overall"],
                summary["by_difficulty"]["easy"],
                summary["by_difficulty"]["medium"],
                summary["by_difficulty"]["hard"],
                str(summary["question_count"]),
                f"{summary['points_per_question']:.2f}",
                f"{summary['avg_steps']:.2f}",
                f"{summary['avg_latency']:.2f}s",
                failure_text,
            ]
        )
    print(_format_table(headers, rows))
    print(
        "\nQuestion counts and percentage-point impact: "
        + "; ".join(
            f"{summary['model']} ({summary['split']}): "
            f"{summary['question_count']} questions, one question = "
            f"{summary['points_per_question']:.2f} percentage points"
            for summary in summaries
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
