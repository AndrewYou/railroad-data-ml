import datetime as dt
import os

import psycopg
import pytest

from rail import db
from rail.load import load

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://rail:rail@localhost:5432/rail_test")
SINCE = dt.date(2021, 1, 1)
ACTIVE = ("BNSF", "UP", "NS", "CSX", "CN", "CPKC")


@pytest.fixture
def conn():
    """A fresh schema per test."""
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS core, ops, mart CASCADE")
    db.init(TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as c:
        yield c


def run(conn, ds, rows) -> dict:
    """One load as the pipeline runs it: a job_run row, then the load in its own transaction."""
    run_id = conn.execute(
        "INSERT INTO ops.job_run (dataset, status) VALUES (%s, 'running') RETURNING run_id", (ds.name,)).fetchone()[0]
    counts = load(conn, ds, rows, SINCE, run_id)
    conn.commit()
    return counts


def issues(conn, check_name) -> list[tuple]:
    return conn.execute(
        "SELECT action, railroad, week_ending::text, detail FROM ops.issue WHERE check_name = %s ORDER BY railroad",
        (check_name,)).fetchall()


# Fake API rows, shaped like the real JSON (blank values are missing keys) ---------------

def api_date(day: str) -> str:
    return f"{day}T00:00:00.000"


def carload(railroad, commodity, load_type, carloads, week="2026-10-10"):
    row = {"date": api_date(week), "submission_date": api_date("2026-10-14"),
           "railroad": railroad, "commodity": commodity, "type": load_type}
    if carloads is not None:
        row["carloads"] = str(carloads)
    return row


def full_carload_week(conn, week="2026-10-10", railroads=ACTIVE, value=100) -> list[dict]:
    """Every commodity, both load types, for each railroad."""
    commodities = [c for (c,) in conn.execute("SELECT commodity FROM core.commodity")]
    return [carload(r, c, t, value, week) for r in railroads for c in commodities for t in ("Originated", "Received")]


def service(railroad, measure, variable, value, subvariable=None, week="2026-10-09"):
    row = {"measure": measure, "date": api_date(week), "submission_date": api_date("2026-10-14"),
           "railroad": railroad, "variable": variable}
    if subvariable is not None:
        row["subvariable"] = subvariable
    if value is not None:
        row["value"] = str(value)
    return row


SPEED = "Average Train Speed  (MPH)"
DWELL = "Average Terminal Dwell Time (Excluding Cars on Run Through Trains) (Hours)"
CARS_ONLINE = "Cars On Line (Count)"


def full_service_week(railroads=ACTIVE) -> list[dict]:
    """The headline series for each railroad."""
    return [row for r in railroads for row in (
        service(r, SPEED, "System", 24.5), service(r, DWELL, "System Average", 20.1),
        service(r, CARS_ONLINE, "Total", 150000))]
