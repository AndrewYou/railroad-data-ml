"""python -m nowcast: run the walk-forward backtest and this quarter's projection; store both in schema ml."""
import logging

import pandas as pd

from nowcast import backtest
from nowcast.features import checkpoints, load, weekly
from nowcast.model import FEATURES, baseline_growth, fit, model_growth, project
from rail import db

log = logging.getLogger("nowcast")


def live_projections(rows: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """This quarter's projection from both methods, ± the backtest's mean error at the same checkpoint."""
    live = rows[rows["actual"].isna()].dropna(subset=["base_growth"])
    live = live.loc[live.groupby("railroad")["checkpoint"].idxmax()]  # the latest week each railroad has
    typical = backtest.errors(results).groupby("checkpoint")[["baseline", "model"]].mean() / 100
    model = fit(backtest.usable(rows))  # trained on every complete quarter
    out = []
    for method, g in (("baseline", baseline_growth(live)), ("model", model_growth(model, live))):
        projection = project(live["observed"], live["ly_remaining"], g)
        error = typical[method].reindex(live["checkpoint"]).to_numpy()
        out.append(pd.DataFrame({
            "railroad": live["railroad"], "quarter": live["quarter"].astype(str), "checkpoint": live["checkpoint"],
            "method": method, "projection": projection, "low": projection * (1 - error),
            "high": projection * (1 + error), "last_year": live["ly_observed"] + live["ly_remaining"]}))
    return pd.concat(out, ignore_index=True)


def insert(conn, table: str, df: pd.DataFrame) -> None:
    with conn.cursor().copy(f"COPY {table} ({', '.join(df.columns)}) FROM STDIN") as copy:
        for row in df.astype(object).where(df.notna(), None).itertuples(index=False):
            copy.write_row(row)


def save(rows: pd.DataFrame, results: pd.DataFrame, importance: pd.Series, live: pd.DataFrame) -> None:
    """Replace the backtest tables and append this run's live projections, in one transaction."""
    metric = pd.concat([table.reset_index(names="key").assign(scope=scope)
                        for scope, table in backtest.metrics(results).items()])
    with db.connect() as conn:
        trained, tested = backtest.usable(rows)["quarter"], results["quarter"]
        run_id = conn.execute("""
            INSERT INTO ml.run (data_version, winner, train_quarters, test_quarters, first_quarter, test_from, test_to)
            VALUES ((SELECT max(run_id) FROM ops.job_run WHERE status = 'succeeded'), %s, %s, %s, %s, %s, %s)
            RETURNING run_id""", (backtest.winner(results), trained.nunique(), tested.nunique(),
                                  str(trained.min()), str(tested.min()), str(tested.max()))).fetchone()[0]
        conn.execute("TRUNCATE ml.backtest, ml.metric, ml.feature_importance")
        insert(conn, "ml.backtest", results.assign(quarter=results["quarter"].astype(str))
               [["railroad", "quarter", "checkpoint", "actual", "baseline", "model"]])
        insert(conn, "ml.metric", metric.assign(key=metric["key"].astype(str))[["scope", "key", "baseline", "model"]])
        insert(conn, "ml.feature_importance", pd.DataFrame({
            "feature": importance.index, "description": [FEATURES[f] for f in importance.index],
            "importance": importance.to_numpy()}))
        insert(conn, "ml.projection", live.assign(run_id=run_id))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init()
    rows = checkpoints(weekly(*load()))
    results, importance = backtest.walk_forward(rows)
    save(rows, results, importance, live_projections(rows, results))
    overall = backtest.errors(results)[["baseline", "model"]].mean()
    log.info("%s wins: baseline %.2f%%, model %.2f%% mean error over %d test quarters",
             backtest.winner(results), overall["baseline"], overall["model"], results["quarter"].nunique())


if __name__ == "__main__":
    main()
