"""Walk-forward backtest: replay history, training only on quarters that had already ended.

For each test quarter Q: fit on every complete quarter before Q, then project Q at each checkpoint.
"""
import pandas as pd
from sklearn.inspection import permutation_importance

from nowcast.model import FEATURES, baseline_growth, correction, fit, inputs, model_growth, project

MIN_TRAIN_QUARTERS = 4


def usable(rows: pd.DataFrame) -> pd.DataFrame:
    """Complete quarters where both methods can project (the baseline needs a year of history)."""
    return rows.dropna(subset=["target", "yoy_13w"])


def walk_forward(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Projections for every test quarter, and permutation importance averaged over the test rows."""
    rows = usable(rows)
    results, importance = [], []
    for quarter in sorted(rows["quarter"].unique()):
        train, test = rows[rows["quarter"] < quarter], rows[rows["quarter"] == quarter]
        if train["quarter"].nunique() < MIN_TRAIN_QUARTERS:
            continue
        model = fit(train)
        results.append(test.assign(
            last_train_quarter=train["quarter"].max(),
            baseline=project(test["observed"], test["ly_remaining"], baseline_growth(test)),
            model=project(test["observed"], test["ly_remaining"], model_growth(model, test))))
        # Permutation importance: shuffle one feature at a time and measure how much worse the model gets.
        shuffled = permutation_importance(model, inputs(test), correction(test), n_repeats=5, random_state=0,
                                          scoring="neg_mean_absolute_error")
        importance.append(pd.Series(shuffled.importances_mean, index=list(FEATURES)) * len(test))
    results = pd.concat(results, ignore_index=True)
    return results, (sum(importance) / len(results)).sort_values(ascending=False)


def errors(results: pd.DataFrame) -> pd.DataFrame:
    """Absolute % error of each method's quarter total, one row per projection."""
    out = results[["railroad", "quarter", "checkpoint"]].copy()
    for method in ("baseline", "model"):
        out[method] = (results[method] / results["actual"] - 1).abs() * 100
    return out


def metrics(results: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Mean absolute % error: overall, by weeks into the quarter, by railroad and by quarter."""
    err = errors(results)
    methods = ["baseline", "model"]
    return {"overall": err[methods].mean().to_frame("all").T,
            "checkpoint": err.groupby("checkpoint")[methods].mean(),
            "railroad": err.groupby("railroad")[methods].mean(),
            "quarter": err.groupby(err["quarter"].astype(str))[methods].mean()}


def winner(results: pd.DataFrame) -> str:
    """Lower average backtest error wins. Decided on the backtest only, never on the live quarter."""
    overall = errors(results)[["baseline", "model"]].mean()
    return "model" if overall["model"] < overall["baseline"] else "baseline"
