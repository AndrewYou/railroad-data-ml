"""Postgres connection and schema setup."""
import os
from pathlib import Path

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://rail:rail@localhost:5432/rail")
SQL_DIR = Path(__file__).parent.parent / "sql"
SQL_FILES = ("schema.sql", "terminals.sql", "views.sql")  # tables + reference data, then views


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or DATABASE_URL)


def init(url: str | None = None) -> None:
    """Create tables, seed reference data and create views. Safe to run on every start."""
    with connect(url) as conn:
        for name in SQL_FILES:
            conn.execute((SQL_DIR / name).read_text())
