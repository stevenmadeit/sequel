import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MODEL = os.getenv("SEQUEL_MODEL", "qwen2.5-coder:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DATABASE_PATH = PROJECT_ROOT / "sequel.duckdb"
SCHEMA_DOCS_PATH = PROJECT_ROOT / "schema_docs.md"
