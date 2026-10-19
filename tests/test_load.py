"""The load publishes source values faithfully, records restatements, and never deletes."""
from rail.datasets import CARLOADS, SERVICE

from conftest import SPEED, carload, full_carload_week, full_service_week, issues, run, service


def published_carloads(conn):
    return dict(conn.execute(
        "SELECT railroad || ' ' || commodity || ' ' || load_type, carloads FROM core.carloads").fetchall())


def test_values_are_published_as_reported(conn):
    run(conn, CARLOADS, [
        carload("CPKC", "Grain", "Originated", 258.5),  # half cars are real
        carload("UP", "Coke", "Originated", 0),          # zero is a real zero
        carload("NS", "Coal", "Originated", None),       # blank stays NULL
    ])
    assert published_carloads(conn) == {
        "CPKC Grain Originated": 258.5, "UP Coke Originated": 0, "NS Coal Originated": None}


def test_blank_service_value_is_null_and_blank_subvariable_is_empty_string(conn):
    run(conn, SERVICE, [service("UP", SPEED, "System", None)])
    assert conn.execute("SELECT subvariable, value FROM core.service_metric").fetchall() == [("", None)]


def test_restated_value_is_published_and_recorded_as_revision(conn):
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 100)])
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 120)])

    assert published_carloads(conn) == {"UP Grain Originated": 120}
    assert conn.execute("SELECT railroad, series, old_value, new_value FROM ops.revision").fetchall() == [
        ("UP", "Grain / Originated", 100, 120)]


def test_reloading_the_same_data_changes_nothing(conn):
    rows = full_carload_week(conn)
    first = run(conn, CARLOADS, rows)
    second = run(conn, CARLOADS, rows)

    assert first["rows_changed"] == len(rows)
    assert second == {"rows_fetched": len(rows), "rows_changed": 0, "rows_held": 0, "revisions": 0}


def test_row_removed_upstream_is_kept_and_flagged(conn):
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 100), carload("UP", "Coal", "Originated", 50)])
    run(conn, CARLOADS, [carload("UP", "Grain", "Originated", 100)])

    assert published_carloads(conn) == {"UP Grain Originated": 100, "UP Coal Originated": 50}
    assert issues(conn, "removed_upstream") == [
        ("flagged", "UP", "2026-10-10", "no longer in source: Coal / Originated")]


def test_carloads_copy_in_service_dataset_is_not_published(conn):
    run(conn, SERVICE, full_service_week() + [
        service("UP", "Weekly Carloads By 23 Commodity Categories", "Grain", 100, "Originated", week="2026-10-10")])
    assert conn.execute("SELECT DISTINCT measure FROM core.service_metric ORDER BY 1").fetchall() == [
        ("cars_online",), ("terminal_dwell",), ("train_speed",)]
