import re
import threading
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from sequel.config import DATABASE_PATH


def execute_query(query: str, timeout_seconds: float = 5.0) -> list[tuple[Any, ...]]:
    database_path = Path(DATABASE_PATH)
    if not database_path.exists():
        raise FileNotFoundError(
            f"DuckDB database not found at {database_path}. Run build_db.py first."
        )

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
        config={"enable_external_access": "false"},
    )
    timer: threading.Timer | None = None
    try:
        statements = connection.extract_statements(query)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Only one SELECT or WITH ... SELECT is allowed.")
        timer = threading.Timer(timeout_seconds, connection.interrupt)
        timer.daemon = True
        timer.start()
        return connection.execute(query).fetchall()
    except Exception as exc:
        if "interrupt" in str(exc).lower() or "timeout" in str(exc).lower():
            raise TimeoutError(
                f"Query exceeded the {timeout_seconds:g}-second time limit."
            ) from exc
        raise
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    numeric_types = (int, float, Decimal)
    if isinstance(left, numeric_types) and isinstance(right, numeric_types):
        left_number = Decimal(str(left))
        right_number = Decimal(str(right))
        if not left_number.is_finite() or not right_number.is_finite():
            return left_number == right_number
        tolerance = max(
            Decimal("1e-8"),
            Decimal("1e-6") * max(abs(left_number), abs(right_number)),
        )
        return abs(left_number - right_number) <= tolerance
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _values_equal(left_value, right_value)
            for left_value, right_value in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _values_equal(left[key], right[key]) for key in left
        )
    return left == right


def _rows_equal(left: Sequence[Any], right: Sequence[Any]) -> bool:
    return len(left) == len(right) and all(
        _values_equal(left_value, right_value)
        for left_value, right_value in zip(left, right)
    )


def results_equal(
    gold_rows: list[tuple[Any, ...]],
    agent_rows: list[tuple[Any, ...]],
    gold_sql: str,
) -> bool:
    if len(gold_rows) != len(agent_rows):
        return False
    ordered_top_n = bool(
        re.search(r"\border\s+by\b[\s\S]*?\blimit\s+\d+\b", gold_sql, re.IGNORECASE)
    )
    if ordered_top_n:
        return all(
            _rows_equal(gold, actual)
            for gold, actual in zip(gold_rows, agent_rows)
        )

    unmatched = list(agent_rows)
    for gold_row in gold_rows:
        for index, actual_row in enumerate(unmatched):
            if _rows_equal(gold_row, actual_row):
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


_UNANSWERABLE_PATTERNS = (
    r"\bcan(?:not|'t)\s+answer\b",
    r"\bcannot\s+be\s+answered\b",
    r"\bunable\s+to\s+(?:answer|determine|calculate)\b",
    r"\b(?:cannot|can't)\s+(?:be\s+)?(?:determined|calculated|answered|computed)\b",
    r"\b(?:not|isn't|aren't)\s+(?:available|provided|captured|tracked|in the data|in the database)\b",
    r"\bno\s+(?:data|information|records?)\s+(?:about|for|on|to determine)\b",
    r"\bno\s+(?:candidate|application|interview)[\w -]*(?:data|information|table|records?)\b",
    r"\b(?:does not|doesn't|do not|don't)\s+(?:contain|include|track|provide)\b",
    r"\b(?:not enough|insufficient)\s+(?:data|information)\b",
    r"\bnot\s+(?:tracked|recorded|collected|stored)\b",
    r"\boutside\s+the\s+(?:available\s+)?data\b",
)


def says_unanswerable(answer: str) -> bool:
    return any(
        re.search(pattern, answer, re.IGNORECASE)
        for pattern in _UNANSWERABLE_PATTERNS
    )
