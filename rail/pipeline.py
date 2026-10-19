"""Jobs: load both datasets (with run tracking and an email summary), and the hourly watcher."""
import datetime as dt
import logging
import time

from rail import alerts, api, checks, db, datasets
from rail.load import load

log = logging.getLogger(__name__)

CHECK_EVERY = dt.timedelta(hours=1)
BACKSTOP = dt.timedelta(days=7)  # load anyway if nothing has succeeded for this long


def window_start(today: dt.date) -> dt.date:
    """Keep five full calendar years plus the current year."""
    return dt.date(today.year - 5, 1, 1)


def load_all() -> list[int]:
    """Fetch and publish both datasets, one transaction each. Returns the run ids."""
    since = window_start(dt.date.today())
    run_ids = []
    for ds in datasets.ALL:
        run_id = start_run(ds)
        try:
            with db.connect() as conn:  # commits on success, rolls back on any error
                counts = load(conn, ds, api.fetch_rows(ds.socrata_id, since), since, run_id)
            finish_run(run_id, "succeeded", **counts)
        except Exception as e:
            log.exception("%s load failed", ds.name)
            finish_run(run_id, "failed", error=f"{type(e).__name__}: {e}")
        run_ids.append(run_id)

    with db.connect() as conn:
        alerts.send(*alerts.run_summary(conn, run_ids))
    return run_ids


def watch() -> None:
    """Every hour: load if USDA has published new data, and alert if a weekly filing is late."""
    while True:
        try:
            if load_is_due():
                load_all()
            with db.connect() as conn:
                late = checks.flag_stale_data(conn, dt.datetime.now(dt.timezone.utc))
            if late:
                alerts.send("Weekly rail data is late", "\n".join(late))
        except Exception:
            log.exception("watch cycle failed; retrying next cycle")
        time.sleep(CHECK_EVERY.total_seconds())


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
