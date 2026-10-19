"""Jobs: load both datasets (with run tracking and an email summary), and the hourly watcher."""
import datetime as dt
import logging
import subprocess
import sys
import time

from rail import alerts, api, checks, db, datasets
from rail.load import load

log = logging.getLogger(__name__)

CHECK_EVERY = dt.timedelta(hours=1)
BACKSTOP = dt.timedelta(days=7)  # load anyway if nothing has succeeded for this long


HISTORY_START = dt.date(2017, 1, 1)  # the carloads dataset starts 2017-03-25


def window_start(today: dt.date) -> dt.date:
    """What each refresh re-fetches: five full calendar years plus the current year.

    Older weeks are loaded once (backfill from HISTORY_START) and then kept as they are:
    loads never delete, so the full history stays available to the dashboard and the nowcast.
    """
    return dt.date(today.year - 5, 1, 1)


def load_all(since: dt.date | None = None) -> list[int]:
    """Fetch and publish both datasets, one transaction each. Returns the run ids."""
    since = since or window_start(dt.date.today())
    run_ids, all_ok = [], True
    for ds in datasets.ALL:
        run_id = start_run(ds)
        try:
            with db.connect() as conn:  # commits on success, rolls back on any error
                counts = load(conn, ds, api.fetch_rows(ds.socrata_id, since), since, run_id)
            finish_run(run_id, "succeeded", **counts)
        except Exception as e:
            log.exception("%s load failed", ds.name)
            finish_run(run_id, "failed", error=f"{type(e).__name__}: {e}")
            all_ok = False
        run_ids.append(run_id)

    with db.connect() as conn:
        alerts.send(*alerts.run_summary(conn, run_ids))
    if all_ok:
        run_nowcast()
    return run_ids


def run_nowcast() -> None:
    """Refresh the quarter nowcast. A separate process, so rail/ stays free of pandas and scikit-learn,
    and a nowcast failure is reported without failing the data load."""
    result = subprocess.run([sys.executable, "-m", "nowcast"], capture_output=True, text=True)
    if result.returncode:
        log.error("nowcast failed:\n%s", result.stderr)
        alerts.send("Nowcast failed (data load unaffected)", result.stderr[-4000:])


def watch() -> None:
    """Every hour: load if USDA has published new data, and alert if a weekly filing is late."""
    while True:
        try:
            if load_is_due():
                load_all(None if has_loaded() else HISTORY_START)  # the first load backfills full history
            with db.connect() as conn:
                late = checks.flag_stale_data(conn, dt.datetime.now(dt.timezone.utc))
            if late:
                alerts.send("Weekly rail data is late", "\n".join(late))
        except Exception:
            log.exception("watch cycle failed; retrying next cycle")
        time.sleep(CHECK_EVERY.total_seconds())


def has_loaded() -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT count(DISTINCT dataset) = 2 FROM ops.job_run WHERE status = 'succeeded'").fetchone()[0]


def load_is_due() -> bool:
    """True if either dataset changed at the source since our last successful load of it."""
    with db.connect() as conn:
        for ds in datasets.ALL:
            source_updated_at, started_at = conn.execute("""
                SELECT max(source_updated_at), max(started_at) FROM ops.job_run
                WHERE dataset = %s AND status = 'succeeded'""", (ds.name,)).fetchone()
            if started_at is None or started_at < dt.datetime.now(dt.timezone.utc) - BACKSTOP:
                return True
            if api.last_updated(ds.socrata_id) > source_updated_at:
                log.info("%s updated at source", ds.name)
                return True
    return False


# Run tracking: separate short transactions, so a run's status survives its load rolling back.

def start_run(ds: datasets.Dataset) -> int:
    source_updated_at = api.last_updated(ds.socrata_id)
    with db.connect() as conn:
        return conn.execute("""
            INSERT INTO ops.job_run (dataset, status, source_updated_at)
            VALUES (%s, 'running', %s) RETURNING run_id""", (ds.name, source_updated_at)).fetchone()[0]


def finish_run(run_id: int, status: str, error: str | None = None, rows_fetched=None,
               rows_changed=None, rows_held=None, revisions=None) -> None:
    with db.connect() as conn:
        conn.execute("""
            UPDATE ops.job_run
            SET status = %s, finished_at = now(), error = %s, rows_fetched = %s,
                rows_changed = %s, rows_held = %s, revisions = %s
            WHERE run_id = %s""", (status, error, rows_fetched, rows_changed, rows_held, revisions, run_id))
