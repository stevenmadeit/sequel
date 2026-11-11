import asyncio
import json
import logging
import queue
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sequel.agent import AgentFailure, AgentResponse, ask_detailed
from sequel.config import PROJECT_ROOT

logger = logging.getLogger(__name__)
app = FastAPI(title="Sequel API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

_request_slots = threading.BoundedSemaphore(5)
_EVALS_DB = PROJECT_ROOT / "evals" / "results.db"
_QUESTIONS_FILE = PROJECT_ROOT / "evals" / "questions.json"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/ask")
async def ask(request: AskRequest) -> StreamingResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question cannot be blank.")
    if not _request_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="The analyst is busy. Try again shortly.")

    async def stream():
        event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        loop = asyncio.get_running_loop()
        sentinel = object()

        def publish(event: str, data: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(event_queue.put, (event, data))

        def worker() -> None:
            try:
                response: AgentResponse = ask_detailed(question, on_event=publish)
                publish(
                    "final",
                    {"answer": response.answer, "sql": response.sql, "steps": response.steps},
                )
            except AgentFailure as exc:
                publish(
                    "error",
                    {
                        "message": str(exc),
                        "failure_type": exc.failure_type,
                        "steps": exc.steps,
                    },
                )
            except Exception as exc:
                logger.exception("Agent request failed")
                publish("error", {"message": str(exc)})
            finally:
                loop.call_soon_threadsafe(event_queue.put, ("__done__", sentinel))
                _request_slots.release()

        thread = threading.Thread(target=worker, daemon=True)
        try:
            thread.start()
        except Exception:
            _request_slots.release()
            raise
        while True:
            event, data = await asyncio.to_thread(event_queue.get)
            if event == "__done__":
                break
            yield _sse(event, data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/schema")
async def schema() -> dict[str, str]:
    path = PROJECT_ROOT / "schema_docs.md"
    try:
        return {"content": path.read_text(encoding="utf-8")}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read schema docs: {exc}") from exc


@app.get("/evals")
async def evaluations(run_id: str | None = Query(default=None)) -> dict[str, Any]:
    import sqlite3

    if not _EVALS_DB.exists():
        return {"runs": [], "selected_run_id": run_id, "results": []}
    try:
        connection = sqlite3.connect(_EVALS_DB)
        connection.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"runs", "results"}.issubset(tables):
            connection.close()
            raise HTTPException(
                status_code=500, detail="Evaluation database schema is incomplete."
            )
        question_map: dict[str, dict[str, Any]] = {}
        if _QUESTIONS_FILE.exists():
            question_map = {
                item["id"]: item
                for item in json.loads(_QUESTIONS_FILE.read_text(encoding="utf-8"))
            }
        runs = []
        for run in connection.execute(
            "SELECT run_id, model, split, started_at FROM runs ORDER BY started_at DESC"
        ):
            run_results = connection.execute(
                "SELECT difficulty, correct, failure_type, latency, steps "
                "FROM results WHERE run_id = ?",
                (run["run_id"],),
            ).fetchall()
            total = len(run_results)
            if not total:
                continue
            correct = sum(row["correct"] for row in run_results)
            by_difficulty: dict[str, dict[str, int | float]] = {}
            for difficulty in ("easy", "medium", "hard"):
                subset = [row for row in run_results if row["difficulty"] == difficulty]
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
            for row in run_results:
                failure_types[row["failure_type"]] = (
                    failure_types.get(row["failure_type"], 0) + 1
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
                    "average_steps": sum(row["steps"] for row in run_results) / total,
                    "average_latency": sum(row["latency"] for row in run_results) / total,
                }
            )

        selected_results = []
        if run_id is not None:
            if not any(run["run_id"] == run_id for run in runs):
                connection.close()
                raise HTTPException(status_code=404, detail="Evaluation run not found.")
            for row in connection.execute(
                """
                SELECT question_id, difficulty, correct, failure_type, agent_sql,
                       steps, latency, answer, error
                FROM results WHERE run_id = ? ORDER BY question_id
                """,
                (run_id,),
            ):
                question = question_map.get(row["question_id"], {})
                selected_results.append(
                    {
                        **dict(row),
                        "question": question.get("question", row["question_id"]),
                        "gold_sql": question.get("gold_sql"),
                    }
                )
        connection.close()
        return {
            "runs": runs,
            "selected_run_id": run_id,
            "results": selected_results,
        }
    except HTTPException:
        raise
    except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        logger.exception("Could not load evaluation results")
        raise HTTPException(status_code=500, detail=f"Could not load evaluations: {exc}") from exc
