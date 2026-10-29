"""Quarter nowcast: calendar, baseline arithmetic, no look-ahead, and an honest walk-forward."""
import numpy as np
import pandas as pd
import pytest

from nowcast.backtest import MIN_TRAIN_QUARTERS, usable, walk_forward
from nowcast.features import COVID, checkpoints, expected_remaining, quarter_of, quarter_weeks, weekly
from nowcast.model import FEATURES, baseline_growth, project

SATURDAYS = pd.date_range("2023-01-07", "2026-10-10", freq="W-SAT")


def synthetic(value=lambda week: 100.0, railroads=("UP", "CSX")):
    """Weekly carloads per railroad and segment, plus a flat service series."""
    carloads = pd.DataFrame([{"week_ending": w, "railroad": r, "segment": s, "carloads": value(w) * share}
                             for w in SATURDAYS for r in railroads
                             for s, share in (("Intermodal", 0.5), ("Coal", 0.2), ("Merchandise", 0.3))])
    service = pd.DataFrame([{"week_ending": w, "railroad": r, "measure": m, "value": 20.0}
                            for w in SATURDAYS for r in railroads
                            for m in ("train_speed", "terminal_dwell", "cars_online")])
    return carloads, service


def row(rows, railroad, quarter, k):
    return rows.query("railroad == @railroad and quarter == @pd.Period(@quarter) and checkpoint == @k").iloc[0]


# Calendar --------------------------------------------------------------------------------

def test_week_belongs_to_the_quarter_of_its_midpoint():
    weeks = pd.Series(pd.to_datetime(["2026-01-03", "2026-04-04", "2026-03-28"]))
    # Jan 3 week is Dec 28 - Jan 3 (midpoint Dec 31): still Q4. Apr 4 week straddles too, midpoint Apr 1: Q2.
    assert quarter_of(weeks).astype(str).tolist() == ["2025Q4", "2026Q2", "2026Q1"]


def test_quarters_have_12_to_14_weeks():
    assert len(quarter_weeks(pd.Period("2025Q4"))) == 14
    assert len(quarter_weeks(pd.Period("2026Q1"))) == 12  # Q1 is only 90 days
    assert len(quarter_weeks(pd.Period("2026Q2"))) == 13


# Baseline --------------------------------------------------------------------------------

def test_baseline_projection_matches_hand_calculation():
    # 100 carloads a week until 2025-06-28, 120 a week after: 2026 runs 20% above 2025.
    carloads, service = synthetic(lambda w: 120.0 if w > pd.Timestamp("2025-06-28") else 100.0, railroads=("UP",))
    r = row(checkpoints(weekly(carloads, service)), "UP", "2026Q2", 4)

    g = baseline_growth(pd.DataFrame([r])).iloc[0]
    assert g == pytest.approx(1.2)  # trailing 13 weeks: 13 × 120 / 13 × 100, and every earlier year agrees
    # 4 weeks done at 120 = 480; 9 weeks left, 100 each last year = 900; 480 + 1.2 × 900 = 1,560
    assert project(r["observed"], r["ly_remaining"], g) == pytest.approx(1560)
    assert r["actual"] == pytest.approx(1560)


def test_one_unusual_year_does_not_set_the_seasonal_shape():
    # Flat 100 a week, except the back of 2025 Q2 collapsed to 50 (a strike, say). 2026 is back to normal.
    weeks_2025q2 = quarter_weeks(pd.Period("2025Q2"))
    carloads, service = synthetic(lambda w: 50.0 if w in weeks_2025q2[4:] else 100.0, railroads=("UP",))
    r = row(checkpoints(weekly(carloads, service)), "UP", "2026Q2", 4)

    # Last year alone says the 9 remaining weeks bring 450; 2024 and 2023 say 900, and the median wins.
    assert r["ly_remaining"] == pytest.approx(450)
    assert project(r["observed"], r["ly_remaining"], baseline_growth(pd.DataFrame([r])).iloc[0]) == pytest.approx(1300)
    assert r["actual"] == pytest.approx(1300)


def test_covid_weeks_are_skipped_not_just_outvoted():
    # Only 2019-2021 exist: for 2021 Q2 the years back are 2020 (COVID) and 2019. Averaging them would give ~55.
    weeks = pd.date_range("2019-01-05", "2021-07-03", freq="W-SAT")
    total = pd.Series([10.0 if COVID[0] <= w <= COVID[1] else 100.0 for w in weeks], index=weeks)
    remaining = quarter_weeks(pd.Period("2021Q2"))
    assert expected_remaining(total, remaining, remaining[0] - pd.Timedelta(weeks=1)) == pytest.approx(100 * len(remaining))


# No look-ahead -------------------------------------------------------------------------

def test_features_ignore_everything_after_the_checkpoint():
    rng = np.random.default_rng(0)
    noise = {w: rng.uniform(80, 120) for w in SATURDAYS}
    carloads, service = synthetic(lambda w: noise[w])
    before = row(checkpoints(weekly(carloads, service)), "UP", "2026Q2", 5)

    later = carloads["week_ending"] > before["as_of"]
    carloads.loc[later, "carloads"] *= 3  # rewrite the future
    after = row(checkpoints(weekly(carloads, service)), "UP", "2026Q2", 5)

    known = before.drop(["actual", "target"])
    pd.testing.assert_series_equal(after.drop(["actual", "target"]), known)
    assert after["actual"] != before["actual"]  # the outcome did change


# Walk-forward ----------------------------------------------------------------------------

def test_walk_forward_never_trains_on_the_quarter_it_tests():
    rng = np.random.default_rng(1)
    noise = {w: rng.uniform(80, 120) for w in SATURDAYS}
    rows = checkpoints(weekly(*synthetic(lambda w: noise[w])))
    results, importance = walk_forward(rows)

    assert (results["last_train_quarter"] < results["quarter"]).all()  # only quarters that had ended
    quarters = sorted(usable(rows)["quarter"].unique())
    assert results["quarter"].min() == quarters[MIN_TRAIN_QUARTERS]  # first test needs 4 training quarters
    assert set(importance.index) == set(FEATURES)


def test_live_quarter_has_a_projection_basis():
    carloads, service = synthetic()  # data ends 2026-10-10: one week into 2026Q4
    live = checkpoints(weekly(carloads, service)).query("quarter == @pd.Period('2026Q4')")
    assert live["actual"].isna().all()
    assert live["ly_remaining"].notna().all()  # last year's weeks exist even though this year's don't yet
