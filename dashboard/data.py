"""Dashboard data: queries against the mart views, and the comparisons built on them.

Every comparison is to the same weeks a year earlier: week_ending minus 364 days
(52 weeks, so the weekday matches and holidays mostly line up).
"""
import pandas as pd
import psycopg
import streamlit as st
from psycopg.types.numeric import FloatLoader

from rail import db

YEAR = pd.Timedelta(days=364)
RECENT_WEEKS = 4  # "latest" on the map = the last 4 weeks, which smooths one-off weeks
SEGMENTS = ("Intermodal", "Coal", "Merchandise")
PAIRS = {"West: UP vs BNSF": ("UP", "BNSF"), "East: CSX vs NS": ("CSX", "NS")}
SERVICE_METRICS = {  # measure -> (label, unit, higher is better)
    "train_speed": ("Train speed", "mph", True),
    "terminal_dwell": ("Terminal dwell", "hours", False),
    "cars_online": ("Cars online", "cars", False),
}


# Queries: cached until the next successful load ------------------------------------------

@st.cache_data(ttl=60)
def data_version() -> int | None:
    """The latest successful load, or None until both datasets have loaded once. New data shows within a minute."""
    try:
        with db.connect() as conn:
            return conn.execute("""
                SELECT CASE WHEN count(DISTINCT dataset) = 2 THEN max(run_id) END
                FROM ops.job_run WHERE status = 'succeeded'""").fetchone()[0]
    except psycopg.errors.UndefinedTable:  # the worker hasn't created the schema yet
        return None


def query(sql: str) -> pd.DataFrame:
    return _query(sql, data_version())


@st.cache_data
def _query(sql: str, version: int | None) -> pd.DataFrame:
    with db.connect() as conn:
        conn.adapters.register_loader("numeric", FloatLoader)  # numeric -> float, not Decimal
        cur = conn.execute(sql)
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    if "week_ending" in df:
        df["week_ending"] = pd.to_datetime(df["week_ending"])
    return df


def originated() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, commodity, segment, carloads FROM mart.originated")


def commodities() -> pd.DataFrame:
    return query("SELECT commodity, segment, read_through FROM core.commodity")


def active_railroads() -> list[str]:
    return query("SELECT railroad FROM core.railroad WHERE merged_into IS NULL ORDER BY 1")["railroad"].tolist()


def service() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, measure, value FROM mart.service_headline")


def terminal_dwell() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, terminal, dwell_hours, lat, lon FROM mart.terminal_dwell")


def grain_by_state() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, state, cars FROM mart.grain_by_state")


def coal_by_basin() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, basin, loadings FROM mart.coal_by_basin")


def status() -> dict:
    """What the top bar shows: latest week, last load, and anything needing attention."""
    row = query("""
        SELECT (SELECT max(week_ending) FROM core.carloads)            AS carloads_week,
               (SELECT max(week_ending) FROM core.service_metric)      AS service_week,
               (SELECT max(finished_at) FROM ops.job_run WHERE status = 'succeeded') AS loaded_at,
               (SELECT count(*) FROM ops.issue
                 WHERE run_id IN (SELECT max(run_id) FROM ops.job_run GROUP BY dataset)) AS open_issues,
               (SELECT status FROM ops.job_run ORDER BY run_id DESC LIMIT 1) AS last_status""").iloc[0]
    return row.to_dict()


def revisions() -> pd.DataFrame:
    return query("""
        SELECT j.finished_at::date AS loaded_on, r.dataset, r.railroad, r.week_ending, r.series,
               r.old_value, r.new_value, r.new_value - r.old_value AS change
        FROM ops.revision r JOIN ops.job_run j USING (run_id)
        ORDER BY r.revision_id DESC LIMIT 5000""")


# Comparisons ---------------------------------------------------------------------------

def with_last_year(df: pd.DataFrame, keys: list[str], value: str) -> pd.DataFrame:
    """Add `<value>_ly`: the value for the same keys 52 weeks earlier."""
    last_year = (df[[*keys, "week_ending", value]]
                 .assign(week_ending=df["week_ending"] + YEAR)
                 .rename(columns={value: f"{value}_ly"}))
    return df.merge(last_year, on=[*keys, "week_ending"], how="left")


def pct_change(now: pd.Series, before: pd.Series) -> pd.Series:
    """% change; blank (not infinite) when there is nothing to compare against."""
    return (now / before.where(before != 0) - 1) * 100


def quarters(df: pd.DataFrame) -> list[pd.Period]:
    return sorted(df["week_ending"].dt.to_period("Q").unique(), reverse=True)


def quarter_to_date(orig: pd.DataFrame, quarter: pd.Period, by: list[str]) -> pd.DataFrame:
    """Quarter-to-date carloads vs the same weeks last year, and a projection for the full quarter.

    Projection = carloads so far + last year's remaining weeks grown at this quarter's YoY rate.
    """
    start, end = quarter.start_time, quarter.end_time
    latest = orig.loc[orig["week_ending"].between(start, end), "week_ending"].max()

    def total(first, last):
        rows = orig[orig["week_ending"].between(first, last)]
        return rows.groupby(by)["carloads"].sum() if by else pd.Series({"Network": rows["carloads"].sum()})

    qtd = total(start, latest)
    qtd_ly = total(start - YEAR, latest - YEAR)
    rest_ly = total(latest - YEAR + pd.Timedelta(days=1), end - YEAR)
    yoy = pct_change(qtd, qtd_ly)
    out = pd.DataFrame({
        "QTD carloads": qtd,
        "QTD last year": qtd_ly,
        "YoY %": yoy,
        "Projected quarter": qtd + rest_ly.reindex(qtd.index, fill_value=0) * (1 + yoy / 100),
        "Last year's quarter": qtd_ly + rest_ly.reindex(qtd.index, fill_value=0),
    })
    out["Change vs LY"] = out["QTD carloads"] - out["QTD last year"]
    out.attrs["weeks"] = int(((latest - start).days // 7) + 1)
    out.attrs["through"] = str(latest.date())
    return out


def drivers(orig: pd.DataFrame, quarter: pd.Period, by: str) -> pd.DataFrame:
    """Each group's share of the network's YoY change, in percentage points."""
    t = quarter_to_date(orig, quarter, [by])
    network_ly = t["QTD last year"].sum()
    t["Contribution (pp)"] = t["Change vs LY"] / network_ly * 100
    return t.sort_values("Contribution (pp)")


def weekly_volume(orig: pd.DataFrame, by: str | None) -> pd.DataFrame:
    """Weekly originated carloads per group, with last year and a 4-week YoY %."""
    group = orig[by] if by else pd.Series("Network", index=orig.index)
    weekly = orig.assign(group=group).groupby(["group", "week_ending"], as_index=False)["carloads"].sum()
    weekly = with_last_year(weekly, ["group"], "carloads")
    rolled = weekly.sort_values("week_ending").groupby("group")[["carloads", "carloads_ly"]].transform(
        lambda s: s.rolling(RECENT_WEEKS).sum())
    weekly["yoy_4wk"] = pct_change(rolled["carloads"], rolled["carloads_ly"])
    return weekly


def market_share(orig: pd.DataFrame, pair: tuple[str, str], segment: str | None, commodity: str | None):
    """Share of the pair's originated carloads, 13-week rolling, for the first railroad in the pair."""
    rows = orig[orig["railroad"].isin(pair)]
    if segment:
        rows = rows[rows["segment"] == segment]
    if commodity:
        rows = rows[rows["commodity"] == commodity]
    weekly = rows.pivot_table(index="week_ending", columns="railroad", values="carloads", aggfunc="sum")
    rolled = weekly.rolling(13).sum()
    share = (rolled[pair[0]] / rolled.sum(axis=1) * 100).dropna()
    return share.rename(f"{pair[0]} share %").reset_index()


def service_yoy(svc: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Each railroad's metric vs its own same 4 weeks last year, in %."""
    rows = svc[svc["measure"] == measure][["week_ending", "railroad", "value"]]
    rows = with_last_year(rows, ["railroad"], "value").sort_values("week_ending")
    rolled = rows.groupby("railroad")[["value", "value_ly"]].transform(lambda s: s.rolling(RECENT_WEEKS).mean())
    rows["yoy_4wk"] = pct_change(rolled["value"], rolled["value_ly"])
    return rows


def by_week_of_year(series: pd.DataFrame, value: str) -> pd.DataFrame:
    """Reshape a weekly series for a this-year vs last-year vs 5-year-range chart."""
    df = series.assign(year=series["week_ending"].dt.year,
                       week=series["week_ending"].dt.isocalendar().week.astype(int))
    this_year = df["year"].max()
    history = df[df["year"] < this_year].groupby("week")[value].agg(["min", "max"]).rename(
        columns={"min": "range_low", "max": "range_high"})
    pivot = df[df["year"] >= this_year - 1].pivot_table(index="week", columns="year", values=value)
    pivot = pivot.rename(columns={this_year: "This year", this_year - 1: "Last year"})
    return history.join(pivot, how="outer").reset_index()


def recent_vs_last_year(df: pd.DataFrame, keys: list[str], value: str, how: str) -> pd.DataFrame:
    """The latest 4 weeks vs the same 4 weeks last year, per group (for the map)."""
    df = with_last_year(df, keys, value)
    latest = df["week_ending"].max()
    recent = df[df["week_ending"] > latest - pd.Timedelta(weeks=RECENT_WEEKS)]
    out = recent.groupby(keys, as_index=False)[[value, f"{value}_ly"]].agg(how)
    out["yoy"] = pct_change(out[value], out[f"{value}_ly"])
    out.attrs["through"] = str(latest.date())
    return out
