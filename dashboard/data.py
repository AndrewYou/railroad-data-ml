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
WINDOWS = {"1 Week": 1, "2 Weeks": 2, "4 Weeks": 4}  # one comparison window for every YoY view
SEGMENTS = ("Intermodal", "Coal", "Merchandise")
SERVICE_METRICS = {  # measure -> (label, unit, higher is better)
    "train_speed": ("Train Speed", "MPH", True),
    "terminal_dwell": ("Terminal Dwell", "Hours", False),
    "cars_online": ("Cars Online", "Cars", False),
}


# Queries: cached until the next successful load ------------------------------------------

@st.cache_data(ttl=60)
def data_version() -> str | None:
    """Latest successful load and nowcast run, or None until both datasets have loaded once.

    Used as the cache key, so new data (or a new nowcast) shows within a minute.
    """
    try:
        with db.connect() as conn:
            load, nowcast = conn.execute("""
                SELECT (SELECT CASE WHEN count(DISTINCT dataset) = 2 THEN max(run_id) END
                        FROM ops.job_run WHERE status = 'succeeded'),
                       (SELECT max(run_id) FROM ml.run)""").fetchone()
    except psycopg.errors.UndefinedTable:  # the schema hasn't been created yet
        return None
    return None if load is None else f"{load}-{nowcast}"


def query(sql: str) -> pd.DataFrame:
    return _query(sql, data_version())


@st.cache_data
def _query(sql: str, version: str | None) -> pd.DataFrame:
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
    return query("SELECT commodity, segment FROM core.commodity")


def active_railroads() -> list[str]:
    return query("SELECT railroad FROM core.railroad WHERE merged_into IS NULL ORDER BY 1")["railroad"].tolist()


def service() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, measure, value FROM mart.service_headline")


def terminal_dwell() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, terminal, dwell_hours, lat, lon FROM mart.terminal_dwell")


def grain_by_state() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, state, cars FROM mart.grain_by_state")


def grain_orders_by_state() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, state, orders FROM mart.grain_orders_by_state")


def shuttle_turns_by_region() -> pd.DataFrame:
    return query("SELECT week_ending, railroad, region, turns FROM mart.shuttle_turns_by_region")


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


# Nowcast (written by python -m nowcast) -------------------------------------------------

def nowcast_run() -> dict | None:
    run = query("SELECT * FROM ml.run ORDER BY run_id DESC LIMIT 1")
    return None if run.empty else run.iloc[0].to_dict()


def nowcast_backtest() -> pd.DataFrame:
    return query("SELECT railroad, quarter, checkpoint, actual, baseline, model FROM ml.backtest")


def nowcast_projection() -> pd.DataFrame:
    return query("SELECT * FROM ml.projection WHERE run_id = (SELECT max(run_id) FROM ml.run)")


def feature_importance() -> pd.DataFrame:
    return query("SELECT feature, description, importance FROM ml.feature_importance ORDER BY importance DESC")


def backtest_errors(backtest: pd.DataFrame) -> pd.DataFrame:
    """Absolute % error of each method's quarter total, one row per projection."""
    return backtest.assign(**{m: (backtest[m] / backtest["actual"] - 1).abs() * 100 for m in ("baseline", "model")})


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


def total(orig: pd.DataFrame, first, last, by: list[str]) -> pd.Series:
    """Carloads for weeks ending first..last, per group (or one 'Network' row)."""
    rows = orig[orig["week_ending"].between(first, last)]
    return rows.groupby(by)["carloads"].sum() if by else pd.Series({"Network": rows["carloads"].sum()})


def period(first: pd.Timestamp, last: pd.Timestamp) -> dict:
    """Display strings for a period and the same weeks a year earlier."""
    return {"weeks": int((last - first).days // 7 + 1),
            "first": f"{first:%b %d}", "through": f"{last:%b %d, %Y}",
            "first_ly": f"{first - YEAR:%b %d}", "through_ly": f"{last - YEAR:%b %d, %Y}"}


def quarter_to_date(orig: pd.DataFrame, quarter: pd.Period, by: list[str]) -> pd.DataFrame:
    """Quarter-to-date carloads vs the same weeks last year, and a projection for the full quarter.

    Projection = carloads so far + last year's remaining weeks grown at this quarter's YoY rate.
    """
    start, end = quarter.start_time, quarter.end_time
    weeks = orig.loc[orig["week_ending"].between(start, end), "week_ending"]
    first, latest = weeks.min(), weeks.max()
    qtd = total(orig, start, latest, by)
    qtd_ly = total(orig, start - YEAR, latest - YEAR, by)
    rest_ly = total(orig, latest - YEAR + pd.Timedelta(days=1), end - YEAR, by)
    yoy = pct_change(qtd, qtd_ly)
    out = pd.DataFrame({
        "QTD carloads": qtd,
        "QTD last year": qtd_ly,
        "YoY %": yoy,
        "Projected quarter": qtd + rest_ly.reindex(qtd.index, fill_value=0) * (1 + yoy / 100),
        "Last year's quarter": qtd_ly + rest_ly.reindex(qtd.index, fill_value=0),
    })
    out["Change vs LY"] = out["QTD carloads"] - out["QTD last year"]
    out.attrs = period(first, latest)
    return out


def drivers(orig: pd.DataFrame, weeks: int, by: str, top: int = 6) -> pd.DataFrame:
    """The latest `weeks` vs the same weeks last year: each group's change as points of the network's YoY %.

    Contributions add up to the network's YoY %. Groups beyond the `top` largest are folded into one bar.
    """
    last = orig["week_ending"].max()
    first = last - pd.Timedelta(weeks=weeks - 1)
    now, before = total(orig, first, last, [by]), total(orig, first - YEAR, last - YEAR, [by])
    change = (now - before.reindex(now.index, fill_value=0)).sort_values(key=abs, ascending=False)
    if len(change) > top + 1:
        others = change.iloc[top:]
        plural = {"commodity": "Commodities", "railroad": "Railroads", "segment": "Segments"}[by]
        bucket = f"{len(others)} Other {plural}"  # not "All Other", which is a real commodity
        change = pd.concat([change.iloc[:top], pd.Series({bucket: others.sum()})])
    out = pd.DataFrame({"Change vs LY": change, "Contribution (pp)": change / before.sum() * 100})
    out.attrs = period(first, last) | {"network_change": float(now.sum() - before.sum()),
                                       "network_yoy": float((now.sum() / before.sum() - 1) * 100)}
    return out


def weekly_volume(orig: pd.DataFrame, by: str | None, weeks: int) -> pd.DataFrame:
    """Weekly originated carloads per group, and YoY % on rolling `weeks` totals."""
    group = orig[by] if by else pd.Series("Network", index=orig.index)
    weekly = orig.assign(group=group).groupby(["group", "week_ending"], as_index=False)["carloads"].sum()
    weekly = with_last_year(weekly, ["group"], "carloads")
    rolled = weekly.sort_values("week_ending").groupby("group")[["carloads", "carloads_ly"]].transform(
        lambda s: s.rolling(weeks).sum())
    weekly["yoy"] = pct_change(rolled["carloads"], rolled["carloads_ly"])
    return weekly


def market_share(orig: pd.DataFrame, segment: str | None, commodity: str | None) -> pd.DataFrame:
    """Each railroad's share of these railroads' originated carloads, 13-week rolling, one column per railroad."""
    rows = orig
    if segment:
        rows = rows[rows["segment"] == segment]
    if commodity:
        rows = rows[rows["commodity"] == commodity]
    weekly = rows.pivot_table(index="week_ending", columns="railroad", values="carloads", aggfunc="sum")
    rolled = weekly.rolling(13).sum()
    return (rolled.div(rolled.sum(axis=1), axis=0) * 100).dropna(how="all").reset_index()


def service_yoy(svc: pd.DataFrame, measure: str, weeks: int) -> pd.DataFrame:
    """Each railroad's metric (rolling `weeks` average) vs its own same weeks last year, in %."""
    rows = svc[svc["measure"] == measure][["week_ending", "railroad", "value"]]
    rows = with_last_year(rows, ["railroad"], "value").sort_values("week_ending")
    rolled = rows.groupby("railroad")[["value", "value_ly"]].transform(lambda s: s.rolling(weeks).mean())
    rows["yoy"] = pct_change(rolled["value"], rolled["value_ly"])
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


def recent_vs_last_year(df: pd.DataFrame, keys: list[str], value: str, how: str, weeks: int) -> pd.DataFrame:
    """The latest `weeks` vs the same weeks last year, per group (for the map and terminals table)."""
    df = with_last_year(df, keys, value)
    latest = df["week_ending"].max()
    recent = df[df["week_ending"] > latest - pd.Timedelta(weeks=weeks)]
    out = recent.groupby(keys, as_index=False)[[value, f"{value}_ly"]].agg(how)
    out["yoy"] = pct_change(out[value], out[f"{value}_ly"])
    out.attrs["through"] = str(latest.date())
    return out
