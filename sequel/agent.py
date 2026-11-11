import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

import requests

from sequel.config import MODEL, OLLAMA_BASE_URL
from sequel.data import get_schema, run_sql

logger = logging.getLogger("sequel")


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    sql: str
    steps: int


class AgentFailure(RuntimeError):
    def __init__(self, message: str, failure_type: str, steps: int):
        super().__init__(message)
        self.failure_type = failure_type
        self.steps = steps


AgentEventHandler = Callable[[str, dict[str, Any]], None]


SYSTEM_PROMPT = """You are Sequel, a careful text-to-SQL analyst. Use only the available DuckDB data.
On every turn reply with ONLY one JSON object. The allowed objects are:
{"action": "get_schema"}
{"action": "run_sql", "query": "..."}
{"action": "final_answer", "answer": "...", "sql": "..."}

Call get_schema before writing SQL. Use only columns and tables in that schema.
Check whether query results make sense before answering. If the data cannot answer
the question, say so instead of guessing. Include the SQL that produced your
answer in the final_answer object's sql field. For a question that cannot be
answered from the data, explain why and use an empty sql string if no query applies.
Each tool result arrives as a user message prefixed with "TOOL RESULT:".
For top-N counts, select the counts and use a stable secondary sort for ties.
When the question asks for the most frequent item, report every item tied at
the maximum; do not silently return only one. For top-N requests, note any tie
at the cutoff and identify the other tied items.
To count skills appearing together in postings, self-join job_skills on job_id
and pair distinct skills with a.skill < b.skill; do not compare only neighboring
rows with a window function.
For a request for only the most frequent grouped result(s), count in a CTE,
apply RANK() over the count, and filter to rank 1 so the SQL returns only the
maximum and every tie. For day-level questions over publication_date, group by
CAST(publication_date AS DATE), not the full timestamp.

Worked example:
User: Which skills appear together most often?
Assistant: {"action":"get_schema"}
User: TOOL RESULT: ...schema includes job_skills(job_id, skill)...
Assistant: {"action":"run_sql","query":"WITH pairs AS (SELECT a.skill AS skill_1, b.skill AS skill_2, COUNT(*) AS postings FROM job_skills a JOIN job_skills b ON a.job_id=b.job_id AND a.skill<b.skill GROUP BY a.skill,b.skill), ranked AS (SELECT skill_1, skill_2, postings, RANK() OVER (ORDER BY postings DESC) AS position FROM pairs) SELECT skill_1, skill_2, postings FROM ranked WHERE position=1 ORDER BY skill_1,skill_2"}
User: TOOL RESULT: {"columns":["skill_1","skill_2","postings"],"rows":[["Python","Docker",42],["Python","SQL",42]],"row_count":2,"truncated":false}
Assistant: {"action":"final_answer","answer":"Python and Docker and Python and SQL tie at 42 postings.","sql":"WITH pairs AS (SELECT a.skill AS skill_1, b.skill AS skill_2, COUNT(*) AS postings FROM job_skills a JOIN job_skills b ON a.job_id=b.job_id AND a.skill<b.skill GROUP BY a.skill,b.skill), ranked AS (SELECT skill_1, skill_2, postings, RANK() OVER (ORDER BY postings DESC) AS position FROM pairs) SELECT skill_1, skill_2, postings FROM ranked WHERE position=1 ORDER BY skill_1,skill_2"}
"""


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE).replace("```", "")
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("No JSON object found.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(cleaned[start : index + 1])
                if not isinstance(value, dict):
                    raise ValueError("JSON response must be an object.")
                return value
    raise ValueError("JSON object was incomplete.")


def _validate_action(action: dict[str, Any]) -> None:
    kind = action.get("action")
    if kind == "get_schema":
        return
    if kind == "run_sql" and isinstance(action.get("query"), str):
        return
    if (
        kind == "final_answer"
        and isinstance(action.get("answer"), str)
        and isinstance(action.get("sql"), str)
    ):
        return
    raise ValueError("JSON object does not match an allowed action.")


def _chat(messages: list[dict[str, str]], model: str | None = None) -> str:
    response = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        json={
            "model": model or MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("Ollama response did not contain message.content.")
    return content


def _short_summary(result: str) -> str:
    return " ".join(result.split())[:180]


def ask_detailed(
    question: str,
    model: str | None = None,
    on_event: AgentEventHandler | None = None,
) -> AgentResponse:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    last_successful_sql = ""
    steps = 0

    for iteration in range(1, 9):
        action: dict[str, Any] | None = None
        for retry in range(3):
            steps += 1
            raw_reply = _chat(messages, model)
            try:
                action = _extract_json_object(raw_reply)
                _validate_action(action)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                if on_event is not None:
                    on_event(
                        "result",
                        {
                            "step": steps,
                            "error": True,
                            "summary": (
                                "Invalid JSON response; asking the model to retry. "
                                f"{exc}"
                            ),
                        },
                    )
                messages.append({"role": "assistant", "content": raw_reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your reply was not valid JSON for the required action "
                            f"protocol ({exc}). Reply again with ONLY one allowed JSON object."
                        ),
                    }
                )
                if retry == 2:
                    raise AgentFailure(
                        "Ollama failed to return a valid JSON action after 2 retries.",
                        "invalid_json",
                        steps,
                    ) from exc

        if action is None:
            raise AgentFailure(
                "Ollama did not return a valid action.", "invalid_json", steps
            )
        messages.append({"role": "assistant", "content": json.dumps(action)})
        kind = action["action"]
        if on_event is not None:
            action_data: dict[str, Any] = {"step": iteration, "tool": kind}
            if kind == "run_sql":
                action_data["sql"] = action["query"]
            on_event("action", action_data)
        if kind == "final_answer":
            answer = action["answer"].strip()
            sql = last_successful_sql
            if action["sql"].strip() != sql:
                logger.warning(
                    "Final SQL did not match the query executed; reporting the executed SQL."
                )
            logger.info("[%d/8] final_answer -> %s", iteration, _short_summary(answer))
            return AgentResponse(answer, sql, steps)

        if kind == "get_schema":
            result = get_schema()
        else:
            result = run_sql(action["query"])
            if not result.startswith("SQL error:"):
                last_successful_sql = action["query"].strip()

        logger.info("[%d/8] %s -> %s", iteration, kind, _short_summary(result))
        if on_event is not None:
            error = result.startswith("SQL error:")
            result_data: dict[str, Any] = {
                "step": iteration,
                "error": error,
                "summary": _short_summary(result),
            }
            if kind == "run_sql" and not error:
                try:
                    rows_payload = json.loads(result)
                except json.JSONDecodeError:
                    pass
                else:
                    result_data.update(
                        {
                            "columns": rows_payload.get("columns", []),
                            "rows": rows_payload.get("rows", []),
                            "truncated": rows_payload.get("truncated", False),
                        }
                    )
            on_event("result", result_data)
        messages.append({"role": "user", "content": f"TOOL RESULT: {result}"})

    raise AgentFailure(
        "The agent did not finish within 8 iterations.", "hit_iteration_cap", steps
    )


def ask(question: str) -> tuple[str, str]:
    result = ask_detailed(question)
    return result.answer, result.sql
