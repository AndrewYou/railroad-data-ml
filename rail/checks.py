"""Data checks. Each one answers: would an analyst be misled by what we publish?

Row checks run before publishing and hold failing rows back (action 'held').
Dataset checks run after publishing and record an issue for an engineer (action 'flagged').
Every result lands in ops.issue.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from rail.datasets import CARLOADS, SERVICE, SERVICE_CARLOADS_COPY, Dataset

ET = ZoneInfo("America/New_York")

# Headline service series every active railroad should report each week.
HEADLINE_SERVICE = (("train_speed", "System"), ("terminal_dwell", "System Average"), ("cars_online", "Total"))


# Row checks ---------------------------------------------------------------------------

def hold_invalid_rows(conn, ds: Dataset, run_id: int) -> int:
    """Unknown railroad, commodity or measure, or a missing field.

    A new code usually means a merger or a renamed category: publishing it would put
    rows in the wrong place (or nowhere), so hold it until someone maps it in schema.sql.
    """
    return conn.execute("""
        INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail, source_row)
        SELECT %s, %s, 'invalid_row', 'held', railroad, week_ending, problem, source_row
        FROM clean WHERE problem IS NOT NULL
        """, (run_id, ds.name)).rowcount


def hold_duplicate_keys(conn, ds: Dataset, run_id: int) -> int:
    """Two source rows for the same series and week: we can't tell which is right, so hold both."""
    keys = ", ".join(ds.keys)
    return conn.execute(f"""
        WITH duplicates AS (
            UPDATE clean SET problem = 'duplicate key in source'
            WHERE problem IS NULL AND ({keys}) IN (
                SELECT {keys} FROM clean WHERE problem IS NULL GROUP BY {keys} HAVING count(*) > 1)
            RETURNING railroad, week_ending, problem, source_row)
        INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail, source_row)
        SELECT %s, %s, 'duplicate_key', 'held', railroad, week_ending, problem, source_row FROM duplicates
        """, (run_id, ds.name)).rowcount


# Dataset checks -----------------------------------------------------------------------

def flag_removed_upstream(conn, ds: Dataset, run_id: int, since: dt.date) -> None:
    """A row we published is no longer in the source. We keep it, but someone should find out why."""
    conn.execute(f"""
        INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail)
        SELECT %s, %s, 'removed_upstream', 'flagged', p.railroad, p.week_ending,
               'no longer in source: ' || {ds.series_label('p')}
        FROM {ds.table} p
        WHERE p.week_ending >= %s
          AND NOT EXISTS (SELECT 1 FROM clean c WHERE {ds.key_match('c', 'p')})
        """, (run_id, ds.name, since))


def flag_incomplete_latest_week(conn, ds: Dataset, run_id: int) -> None:
    """Every active railroad reported the latest week in full.

    Without this, a railroad that didn't file (or whose rows were held) shows up as
    a volume drop instead of a gap.
    """
    if ds is CARLOADS:
        conn.execute("""
            WITH latest AS (SELECT max(week_ending) AS week_ending FROM clean),
                 expected AS (SELECT 2 * count(*) AS n FROM core.commodity)  -- originated + received
            INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail)
            SELECT %s, 'carloads', 'incomplete_week', 'flagged', r.railroad, latest.week_ending,
                   format('%%s of %%s commodity rows published', count(p.railroad), expected.n)
            FROM core.railroad r
            CROSS JOIN latest CROSS JOIN expected
            LEFT JOIN core.carloads p ON p.railroad = r.railroad AND p.week_ending = latest.week_ending
            WHERE r.merged_into IS NULL
            GROUP BY r.railroad, latest.week_ending, expected.n
            HAVING count(p.railroad) < expected.n
            """, (run_id,))
    elif ds is SERVICE:
        conn.execute("""
            WITH latest AS (SELECT max(week_ending) AS week_ending FROM clean),
                 headline (measure, variable) AS (SELECT * FROM unnest(%s::text[], %s::text[]))
            INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail)
            SELECT %s, 'service', 'incomplete_week', 'flagged', r.railroad, latest.week_ending,
                   format('%%s / %%s not reported', h.measure, h.variable)
            FROM core.railroad r
            CROSS JOIN latest CROSS JOIN headline h
            LEFT JOIN core.service_metric p
                   ON p.railroad = r.railroad AND p.week_ending = latest.week_ending
                  AND p.measure = h.measure AND p.variable = h.variable AND p.subvariable = ''
            WHERE r.merged_into IS NULL AND p.value IS NULL
            """, ([m for m, _ in HEADLINE_SERVICE], [v for _, v in HEADLINE_SERVICE], run_id))


def flag_carloads_mismatch(conn, run_id: int) -> None:
    """The two USDA datasets agree on each railroad's weekly carloads.

    The service dataset carries its own copy of the carloads. If the totals differ,
    one of the sources (or our load) is wrong. The carloads dataset stays the one we publish.
    """
    conn.execute("""
        WITH service_copy AS (
            SELECT railroad, date::timestamp::date AS week_ending, sum(value::numeric) AS carloads
            FROM stage WHERE measure = %s
            GROUP BY 1, 2),
        published AS (
            SELECT railroad, week_ending, sum(carloads) AS carloads
            FROM core.carloads
            WHERE week_ending >= (SELECT min(week_ending) FROM service_copy)
            GROUP BY 1, 2)
        INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail)
        SELECT %s, 'service', 'carloads_mismatch', 'flagged', railroad, week_ending,
               format('carloads dataset total %%s vs service dataset copy %%s', p.carloads, s.carloads)
        FROM service_copy s JOIN published p USING (railroad, week_ending)
        WHERE s.carloads IS DISTINCT FROM p.carloads
        """, (SERVICE_CARLOADS_COPY, run_id))


def flag_unmapped_terminals(conn, run_id: int) -> None:
    """A terminal an active railroad reports has no map coordinates, so the map would silently omit it.

    Fix by adding it to sql/terminals.sql.
    """
    conn.execute("""
        INSERT INTO ops.issue (run_id, dataset, check_name, action, railroad, week_ending, detail)
        SELECT DISTINCT %s, 'service', 'unmapped_terminal', 'flagged', c.railroad, c.week_ending,
               'no coordinates for terminal: ' || c.variable
        FROM clean c
        JOIN core.railroad r ON r.railroad = c.railroad AND r.merged_into IS NULL
        WHERE c.measure = 'terminal_dwell' AND c.variable <> 'System Average'
          AND c.week_ending = (SELECT max(week_ending) FROM clean)
          AND NOT EXISTS (SELECT 1 FROM core.terminal t WHERE t.railroad = c.railroad AND t.terminal = c.variable)
        """, (run_id,))


# Freshness (runs from the watcher, outside any load) ------------------------------------

def expected_submission(now: dt.datetime) -> dt.date:
    """The latest Wednesday filing that should be loaded by `now`.

    Railroads file on Wednesday and USDA republishes about a day later, so we allow until Friday noon ET.
    """
    now = now.astimezone(ET)
    wednesday = now.date() - dt.timedelta(days=(now.weekday() - 2) % 7)
    if now < dt.datetime.combine(wednesday + dt.timedelta(days=2), dt.time(12), ET):
        wednesday -= dt.timedelta(days=7)
    return wednesday


def flag_stale_data(conn, now: dt.datetime) -> list[str]:
    """This week's filing hasn't arrived: USDA is late or our pipeline is broken.

    Records each stale filing once. Returns the new issues, for alerting.
    """
    expected = expected_submission(now)
    new_issues = []
    for ds in (CARLOADS, SERVICE):
        latest = conn.execute(f"SELECT max(submission_date) FROM {ds.table}").fetchone()[0]
        if latest is not None and latest >= expected:
            continue
        detail = f"no filing for {expected} (latest loaded: {latest})"
        inserted = conn.execute("""
            INSERT INTO ops.issue (dataset, check_name, action, detail)
            SELECT %s, 'stale_data', 'flagged', %s
            WHERE NOT EXISTS (SELECT 1 FROM ops.issue
                              WHERE dataset = %s AND check_name = 'stale_data' AND detail = %s)
            """, (ds.name, detail, ds.name, detail)).rowcount
        if inserted:
            new_issues.append(f"{ds.name}: {detail}")
    return new_issues
