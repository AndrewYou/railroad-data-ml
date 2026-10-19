"""Load one dataset into core: stage -> hold bad rows -> record revisions -> publish -> check.

Runs inside the caller's transaction, so if anything raises, core is left unchanged.
Rows are only ever inserted or updated, never deleted: a short or truncated fetch
can't wipe published history.
"""
import datetime as dt
from collections.abc import Iterable

from rail import checks
from rail.datasets import SERVICE, Dataset


def load(conn, ds: Dataset, rows: Iterable[dict], since: dt.date, run_id: int) -> dict:
    """Publish the rows that pass every row check; record everything else. Returns counts for ops.job_run."""
    rows_fetched = stage(conn, ds, rows)
    conn.execute(f"CREATE TEMP TABLE clean ON COMMIT DROP AS {ds.clean_sql}")

    rows_held = checks.hold_invalid_rows(conn, ds, run_id) + checks.hold_duplicate_keys(conn, ds, run_id)
    revisions = record_revisions(conn, ds, run_id)
    rows_changed = publish(conn, ds)

    checks.flag_removed_upstream(conn, ds, run_id, since)
    checks.flag_incomplete_latest_week(conn, ds, run_id)
    if ds is SERVICE:
        checks.flag_carloads_mismatch(conn, run_id)
        checks.flag_unmapped_terminals(conn, run_id)

    return {"rows_fetched": rows_fetched, "rows_changed": rows_changed,
            "rows_held": rows_held, "revisions": revisions}


def stage(conn, ds: Dataset, rows: Iterable[dict]) -> int:
    """Copy API rows as-is (all text) into a temp table."""
    columns = ", ".join(ds.source_fields)
    conn.execute(f"CREATE TEMP TABLE stage ({', '.join(f'{f} text' for f in ds.source_fields)}) ON COMMIT DROP")
    with conn.cursor().copy(f"COPY stage ({columns}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row([row.get(f) for f in ds.source_fields])  # missing field -> NULL
    return conn.execute("SELECT count(*) FROM stage").fetchone()[0]


def record_revisions(conn, ds: Dataset, run_id: int) -> int:
    """Log every published value that the source has since changed (a restatement)."""
    return conn.execute(f"""
        INSERT INTO ops.revision (run_id, dataset, railroad, week_ending, series, old_value, new_value)
        SELECT %s, %s, c.railroad, c.week_ending, {ds.series_label('c')}, p.{ds.value}, c.{ds.value}
        FROM clean c
        JOIN {ds.table} p ON {ds.key_match('p', 'c')}
        WHERE c.problem IS NULL AND p.{ds.value} IS DISTINCT FROM c.{ds.value}
        """, (run_id, ds.name)).rowcount


def publish(conn, ds: Dataset) -> int:
    """Upsert the rows that passed the row checks. Returns rows inserted or changed."""
    columns = ", ".join((*ds.keys, "submission_date", ds.value))
    return conn.execute(f"""
        INSERT INTO {ds.table} ({columns})
        SELECT {columns} FROM clean WHERE problem IS NULL
        ON CONFLICT ({', '.join(ds.keys)}) DO UPDATE
           SET {ds.value} = EXCLUDED.{ds.value}, submission_date = EXCLUDED.submission_date, updated_at = now()
         WHERE ({ds.table}.{ds.value}, {ds.table}.submission_date)
               IS DISTINCT FROM (EXCLUDED.{ds.value}, EXCLUDED.submission_date)
        """).rowcount
