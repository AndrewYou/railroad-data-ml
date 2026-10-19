"""Checkpoint rows for the quarter nowcast: what was known at week k of a quarter, and what happened next.

One row per (railroad, quarter, checkpoint k), where k = weeks of the quarter already reported.
Features only use weeks up to and including week k; the target only uses the weeks after it.
"""
import numpy as np
import pandas as pd
from psycopg.types.numeric import FloatLoader

from rail import db

YEAR = pd.Timedelta(days=364)  # 52 weeks: same weekday, so each week has its own prior-year match
MAX_CHECKPOINT = 12
SEGMENTS = ("Intermodal", "Coal", "Merchandise")
SERVICE = {"train_speed": "speed", "terminal_dwell": "dwell", "cars_online": "cars_online"}


# Data ----------------------------------------------------------------------------------

def query(sql: str) -> pd.DataFrame:
    with db.connect() as conn:
        conn.adapters.register_loader("numeric", FloatLoader)
        cur = conn.execute(sql)
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    return df


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    carloads = query("""SELECT week_ending, railroad, segment, sum(carloads) AS carloads
                        FROM mart.originated GROUP BY 1, 2, 3""")
    # Service weeks end Friday, carload weeks Saturday. Both come from the same Wednesday filing, so
    # shifting service by one day joins them on the filing (CLAUDE.md rule 1), not on the calendar.
    service = query("""SELECT week_ending + 1 AS week_ending, railroad, measure, value
                       FROM mart.service_headline""")
    return carloads, service


# Calendar ------------------------------------------------------------------------------

def quarter_of(week_ending: pd.Series) -> pd.Series:
    """The calendar quarter containing the week's midpoint (week_ending - 3 days)."""
    return (week_ending - pd.Timedelta(days=3)).dt.to_period("Q")


def quarter_weeks(quarter: pd.Period) -> pd.DatetimeIndex:
    """The Saturdays whose week belongs to `quarter`: 12 to 14 of them (Q1 has only 90 or 91 days)."""
    return pd.date_range(quarter.start_time + pd.Timedelta(days=3),
                         quarter.end_time.normalize() + pd.Timedelta(days=3), freq="W-SAT")


def is_holiday_week(week_ending: pd.DatetimeIndex) -> np.ndarray:
    """Weeks containing Christmas or New Year's Day, the lowest-volume weeks of every year."""
    def contains_holiday(end: pd.Timestamp) -> bool:
        start = end - pd.Timedelta(days=6)
        holidays = [pd.Timestamp(start.year, 12, 25), pd.Timestamp(end.year, 1, 1)]
        return any(start <= h <= end for h in holidays)
    return np.array([contains_holiday(w) for w in week_ending])


# Weekly series -------------------------------------------------------------------------

def log_ratio(now: pd.Series, before: pd.Series) -> pd.Series:
    """log(now / before): growth and decline are symmetric. NaN when there's nothing to compare."""
    return np.log(now / before.where(before > 0))


def growth(now: float, before: float) -> float:
    """log_ratio for single numbers."""
    return float(np.log(now / before)) if before > 0 else np.nan


def weekly(carloads: pd.DataFrame, service: pd.DataFrame) -> pd.DataFrame:
    """One row per railroad and week: volumes, service, their values 52 weeks earlier, and trailing ratios.

    Every column at week w uses only weeks up to w.
    """
    wide = carloads.pivot_table(index=["railroad", "week_ending"], columns="segment",
                                values="carloads", aggfunc="sum").reindex(columns=list(SEGMENTS)).fillna(0)
    wide["total"] = wide.sum(axis=1)
    wide["network"] = wide.groupby(level="week_ending")["total"].transform("sum")
    svc = service.pivot_table(index=["railroad", "week_ending"], columns="measure", values="value")
    wide = wide.join(svc.reindex(columns=list(SERVICE)).rename(columns=SERVICE), how="left")

    last_year = wide.reset_index().assign(week_ending=lambda d: d["week_ending"] + YEAR)
    wide = wide.join(last_year.set_index(["railroad", "week_ending"]).add_suffix("_ly"), how="left")
    wide = wide.sort_index()

    by_railroad = wide.groupby(level="railroad")

    def trailing(column: str, weeks: int, how: str = "sum") -> pd.Series:
        return by_railroad[column].transform(lambda s: s.rolling(weeks).agg(how))

    out = pd.DataFrame(index=wide.index)
    out["total"], out["total_ly"] = wide["total"], wide["total_ly"]
    out["yoy_4w"] = log_ratio(trailing("total", 4), trailing("total_ly", 4))
    out["yoy_13w"] = log_ratio(trailing("total", 13), trailing("total_ly", 13))
    for segment in SEGMENTS:
        out[f"{segment.lower()}_yoy_13w"] = log_ratio(trailing(segment, 13), trailing(f"{segment}_ly", 13))
    out["network_yoy_13w"] = log_ratio(trailing("network", 13), trailing("network_ly", 13))
    for name in SERVICE.values():
        out[f"{name}_yoy_4w"] = log_ratio(trailing(name, 4, "mean"), trailing(f"{name}_ly", 4, "mean"))
    return out.reset_index()


# Checkpoint rows -----------------------------------------------------------------------

def checkpoints(weekly_rows: pd.DataFrame) -> pd.DataFrame:
    """One row per (railroad, quarter, k): the features as of week k, and the quarter's outcome.

    `actual` and `target` are NaN for a quarter that isn't complete yet (the live quarter).
    """
    rows = []
    for railroad, w in weekly_rows.groupby("railroad"):
        w = w.set_index("week_ending")
        for quarter in quarter_of(w.index.to_series()).unique():
            weeks = quarter_weeks(quarter)
            reported = weeks[weeks.isin(w.index)]
            complete = len(reported) == len(weeks)
            ly_holidays = is_holiday_week(weeks - YEAR)
            holidays = is_holiday_week(weeks)
            for k in range(min(len(reported), MAX_CHECKPOINT, len(weeks) - 1) + 1):
                done, remaining = weeks[:k], weeks[k:]
                as_of = done[-1] if k else weeks[0] - pd.Timedelta(weeks=1)  # last week known at k
                if as_of not in w.index or not done.isin(w.index).all():
                    continue
                observed = w.loc[done, "total"].sum()
                # Last year's weeks are looked up directly: this year's remaining weeks may not exist yet.
                ly_observed = w["total"].reindex(done - YEAR).sum(min_count=k) if k else 0.0
                ly_remaining = w["total"].reindex(remaining - YEAR).sum(min_count=len(remaining))
                actual = w.loc[weeks, "total"].sum() if complete else np.nan
                rows.append({
                    "railroad": railroad, "quarter": quarter, "checkpoint": k, "as_of": as_of,
                    "observed": observed, "ly_observed": ly_observed, "ly_remaining": ly_remaining,
                    "actual": actual, "target": growth(actual - observed, ly_remaining),
                    "qtd_yoy": growth(observed, ly_observed) if k else np.nan,
                    "weeks_remaining": len(remaining),
                    "quarter_of_year": quarter.quarter,
                    "holiday_shift": int(holidays[k:].sum() - ly_holidays[k:].sum()),
                    **w.loc[as_of].drop(["total", "total_ly"]).to_dict(),
                })
    return pd.DataFrame(rows)
