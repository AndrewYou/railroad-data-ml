"""Postgres connection and schema setup."""
import os
from pathlib import Path

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://rail:rail@localhost:5432/rail")
SCHEMA_FILE = Path(__file__).parent.parent / "sql" / "schema.sql"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or DATABASE_URL)


def init(url: str | None = None) -> None:
    """Create tables and seed reference data. Safe to run on every start."""
    with connect(url) as conn:
        conn.execute(SCHEMA_FILE.read_text())
