import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import duckdb

from sequel.config import DATABASE_PATH, PROJECT_ROOT, SCHEMA_DOCS_PATH

TABLES = ("stg_jobs", "job_skills", "skill_trends")

TABLE_DESCRIPTIONS = {
    "stg_jobs": "One cleaned row per job posting.",
    "job_skills": "One row for each recognized skill mentioned in a job posting.",
    "skill_trends": "Daily posting counts for each recognized skill.",
}

COLUMN_DESCRIPTIONS = {
    "ingestion_id": "Identifier of the raw ingested source record.",
    "job_id": "Identifier of the job posting, taken from the source posting.",
    "title": "Job title.",
    "company_name": "Name of the company advertising the job.",
    "category": "Source category assigned to the job posting.",
    "tags": "Tags supplied with the source job posting.",
    "salary": "Salary text supplied with the source job posting.",
    "url": "Link to the original job posting.",
    "publication_date": "Date and time the job posting was published.",
    "description": "Description text from the job posting.",
    "skill": "Recognized skill name, such as Python or SQL.",
    "job_posting_count": "Number of postings for this skill on this publication date.",
}


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _duckdb_type(postgres_type: str, udt_name: str) -> str:
    if postgres_type == "ARRAY":
        return "JSON"
    if postgres_type == "USER-DEFINED":
        return "VARCHAR"
    return {
        "smallint": "SMALLINT",
        "integer": "INTEGER",
        "bigint": "BIGINT",
        "numeric": "DECIMAL",
        "real": "REAL",
        "double precision": "DOUBLE",
        "boolean": "BOOLEAN",
        "date": "DATE",
        "timestamp without time zone": "TIMESTAMP",
        "timestamp with time zone": "TIMESTAMPTZ",
        "json": "JSON",
        "jsonb": "JSON",
        "bytea": "BLOB",
    }.get(postgres_type, "VARCHAR")


def _display_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= 100 else text[:97] + "..."


def _column_description(table: str, column: str) -> str:
    description = COLUMN_DESCRIPTIONS.get(column)
    if description:
        return description
    return f"Value for {column.replace('_', ' ')} in the {table} table."


def build_database() -> Path:
    import psycopg2

    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "POSTGRES_PASSWORD is not set. Add it to the project .env file or "
            "set it in the environment before running build_db.py."
        )

    connection = psycopg2.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password=password,
        dbname="signal",
    )
    temporary_path = PROJECT_ROOT / ".sequel-build.duckdb"
    schema_doc = SCHEMA_DOCS_PATH
    docs_sections = ["# Data schema", ""]
    target_schema = "analytics"
    output = DATABASE_PATH

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type IN ('BASE TABLE', 'VIEW')
                """,
                (target_schema,),
            )
            available_tables = {row[0] for row in cursor.fetchall()}
            missing = set(TABLES) - available_tables
            if missing:
                raise RuntimeError(
                    f"Missing required tables in Postgres schema {target_schema}: "
                    + ", ".join(sorted(missing))
                )

            if temporary_path.exists():
                temporary_path.unlink()
            duck = duckdb.connect(str(temporary_path))
            try:
                for table in TABLES:
                    cursor.execute(
                        """
                        SELECT column_name, data_type, udt_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (target_schema, table),
                    )
                    columns = cursor.fetchall()
                    if not columns:
                        raise RuntimeError(
                            f"Could not read the schema for {target_schema}.{table}."
                        )

                    quoted_columns = [_quote_identifier(column[0]) for column in columns]
                    duck_types = [
                        _duckdb_type(data_type, udt_name)
                        for _, data_type, udt_name in columns
                    ]
                    ddl_columns = ", ".join(
                        f"{name} {type_name}"
                        for name, type_name in zip(quoted_columns, duck_types)
                    )
                    duck.execute(
                        f"CREATE TABLE {_quote_identifier(table)} ({ddl_columns})"
                    )

                    cursor.execute(
                        f"SELECT {', '.join(quoted_columns)} "
                        f"FROM {_quote_identifier(target_schema)}."
                        f"{_quote_identifier(table)}"
                    )
                    rows = cursor.fetchall()
                    converted_rows = []
                    for row in rows:
                        converted_rows.append(
                            tuple(
                                json.dumps(value, ensure_ascii=False, default=str)
                                if isinstance(value, (dict, list))
                                and duck_type == "JSON"
                                else value
                                for value, duck_type in zip(row, duck_types)
                            )
                        )
                    placeholders = ", ".join("?" for _ in columns)
                    duck.executemany(
                        f"INSERT INTO {_quote_identifier(table)} VALUES "
                        f"({placeholders})",
                        converted_rows,
                    )

                    docs_sections.extend(
                        [
                            f"## {table}",
                            "",
                            TABLE_DESCRIPTIONS[table],
                            "",
                            "| Column | Type | Meaning | Example |",
                            "|---|---|---|---|",
                        ]
                    )
                    samples = rows[:3]
                    for index, (column, postgres_type, _) in enumerate(columns):
                        example_values = []
                        for sample in samples:
                            value = sample[index]
                            if value is not None:
                                example_values.append(_display_value(value))
                        example = ", ".join(example_values) if example_values else "No sample value"
                        meaning = _column_description(table, column)
                        docs_sections.append(
                            f"| `{column}` | {postgres_type} | {meaning} | "
                            f"{example.replace('|', '\\|')} |"
                        )
                    docs_sections.append("")
                    docs_sections.append(f"Sample rows available: {len(samples)}.")
                    docs_sections.append("")
            finally:
                duck.close()

        schema_doc.write_text("\n".join(docs_sections), encoding="utf-8")
        os.replace(temporary_path, output)
        return output
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise
    finally:
        connection.close()


def run_sql(query: str, timeout_seconds: float = 5.0) -> str:
    """Run one read-only SELECT and return a JSON result or a SQL error."""
    database_path = Path(DATABASE_PATH)
    if not database_path.exists():
        return f"SQL error: database not found at {database_path}. Run build_db.py first."

    if (
        re.search(r"\bgroup\s+by\b", query, re.IGNORECASE)
        and re.search(r"\border\s+by\b", query, re.IGNORECASE)
        and re.search(r"\blimit\s+1\b", query, re.IGNORECASE)
    ):
        return (
            "SQL error: a grouped ranking with LIMIT 1 can hide tied maxima. "
            "Remove LIMIT 1 or use RANK() so all tied results are returned."
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
            return "SQL error: only one SELECT or WITH ... SELECT statement is allowed."

        timer = threading.Timer(timeout_seconds, connection.interrupt)
        timer.daemon = True
        timer.start()
        result = connection.execute(query)
        columns = [description[0] for description in result.description]
        fetched_rows = result.fetchmany(51)
        rows = fetched_rows[:50]
        payload = {
            "columns": columns,
            "rows": [list(row) for row in rows],
            "row_count": len(rows),
            "truncated": len(fetched_rows) > 50,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        error = str(exc)
        if "interrupt" in error.lower() or "timeout" in error.lower():
            return f"SQL error: query exceeded the {timeout_seconds:g}-second time limit."
        return f"SQL error: {error}"
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def get_schema() -> str:
    try:
        return SCHEMA_DOCS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "schema_docs.md is missing. Run build_db.py to generate it from Postgres."
        ) from exc
