"""Each check catches the fault it exists for, and publishes nothing it shouldn't."""
import datetime as dt

from rail.checks import ET, expected_submission, flag_stale_data
from rail.datasets import CARLOADS, SERVICE

from conftest import (CARS_ONLINE, api_date, carload, full_carload_week, full_service_week, issues, run,
                      service)


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_complete_week_raises_no_issues(conn):
    run(conn, CARLOADS, full_carload_week(conn))
    run(conn, SERVICE, full_service_week())
    assert count(conn, "ops.issue") == 0


# Row checks: failing rows are held back, everything else publishes ---------------------

def test_unknown_commodity_is_held_and_the_rest_published(conn):
    rows = full_carload_week(conn) + [carload("UP", "Frac Sand", "Originated", 10)]
    counts = run(conn, CARLOADS, rows)

    assert counts["rows_held"] == 1
    assert count(conn, "core.carloads") == len(rows) - 1
    assert issues(conn, "invalid_row") == [("held", "UP", "2026-10-10", "unknown commodity: Frac Sand")]


def test_unknown_railroad_is_held(conn):
    run(conn, CARLOADS, [carload("UPNS", "Grain", "Originated", 10)])
    assert count(conn, "core.carloads") == 0
    assert issues(conn, "invalid_row") == [("held", "UPNS", "2026-10-10", "unknown railroad: UPNS")]


def test_unknown_measure_is_held(conn):
    run(conn, SERVICE, [service("UP", "Average Train Speed (MPH)", "System", 24.5)])  # one space: renamed
    assert count(conn, "core.service_metric") == 0
    assert issues(conn, "invalid_row") == [
        ("held", "UP", "2026-10-09", "unknown measure: Average Train Speed (MPH)")]


def test_held_row_keeps_the_last_good_value(conn):
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 100)])
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 100), carload("UP", "Grain", "Originated", 999)])

    assert conn.execute("SELECT carloads FROM core.carloads").fetchall() == [(100,)]
    assert len(issues(conn, "duplicate_key")) == 2


# Dataset checks: flagged for an engineer ------------------------------------------------

def test_railroad_missing_from_latest_week_is_flagged(conn):
    run(conn, CARLOADS, full_carload_week(conn, railroads=("BNSF", "UP", "CSX", "CN", "CPKC")))  # no NS
    assert issues(conn, "incomplete_week") == [("flagged", "NS", "2026-10-10", "0 of 46 commodity rows published")]


def test_held_rows_make_the_week_incomplete(conn):
    rows = full_carload_week(conn)
    next(r for r in rows if r["railroad"] == "CSX")["type"] = "Originatd"
    run(conn, CARLOADS, rows)
    assert issues(conn, "incomplete_week") == [("flagged", "CSX", "2026-10-10", "45 of 46 commodity rows published")]


def test_missing_headline_service_metric_is_flagged(conn):
    rows = [r for r in full_service_week() if not (r["railroad"] == "CN" and r["measure"] == CARS_ONLINE)]
    run(conn, SERVICE, rows)
    assert issues(conn, "incomplete_week") == [("flagged", "CN", "2026-10-09", "cars_online / Total not reported")]


def test_carloads_mismatch_between_datasets_is_flagged(conn):
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 100), carload("UP", "Grain", "Received", 20)])
    copy = "Weekly Carloads By 23 Commodity Categories"
    run(conn, SERVICE, full_service_week() + [
        service("UP", copy, "Grain", 100, "Originated", week="2026-10-10"),
        service("UP", copy, "Grain", 25, "Received", week="2026-10-10")])

    assert issues(conn, "carloads_mismatch") == [
        ("flagged", "UP", "2026-10-10", "carloads dataset total 120 vs service dataset copy 125")]


# Freshness ------------------------------------------------------------------------------

def at(day, hour):
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hour), ET)


def test_filing_is_expected_by_friday_noon():
    assert expected_submission(at("2026-10-15", 9)) == dt.date(2026, 10, 7)   # Thursday: last week's filing
    assert expected_submission(at("2026-10-16", 11)) == dt.date(2026, 10, 7)  # Friday morning: still grace
    assert expected_submission(at("2026-10-16", 13)) == dt.date(2026, 10, 14)  # Friday afternoon: this week's
    assert expected_submission(at("2026-10-20", 9)) == dt.date(2026, 10, 14)  # following Tuesday


def test_late_filing_is_flagged_once(conn):
    last_week = [r | {"submission_date": api_date("2026-10-07")} for r in full_carload_week(conn, week="2026-10-03")]
    run(conn, CARLOADS, last_week)            # carloads stuck on last week's filing
    run(conn, SERVICE, full_service_week())   # service has this week's

    first = flag_stale_data(conn, at("2026-10-16", 13))
    second = flag_stale_data(conn, at("2026-10-16", 14))
    assert first == ["carloads: no filing for 2026-10-14 (latest loaded: 2026-10-07)"]
    assert second == []


def test_terminal_without_map_coordinates_is_flagged(conn):
    dwell = "Average Terminal Dwell Time (Excluding Cars on Run Through Trains) (Hours)"
    run(conn, SERVICE, full_service_week() + [
        service("UP", dwell, "Roseville, CA", 22.0),       # has coordinates
        service("UP", dwell, "New Yard, TX", 30.0)])       # doesn't
    assert issues(conn, "unmapped_terminal") == [
        ("flagged", "UP", "2026-10-09", "no coordinates for terminal: New Yard, TX")]
