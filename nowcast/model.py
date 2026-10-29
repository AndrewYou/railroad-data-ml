"""Quarter projections. Both methods use one formula and differ only in the growth rate g:

    projection = carloads already reported this quarter + g × the same remaining weeks last year

The baseline is a seasonal run-rate: the remaining weeks at this year's level, shaped like the median
of up to 3 earlier years with COVID skipped (features.expected_remaining). It replaced the 1-year
run-rate, which carried last year's shocks into this year (2.35% -> 1.92% over 30 backtest quarters).

The model predicts a *correction* to the baseline's growth, not the growth itself. Why: the
run-rate is already very good, and the first version, which learned growth from scratch, did worse
because a few years of quarters is too little to relearn what the run-rate already knows. Predicting
the correction starts the model at the baseline, so with weak evidence it stays close to it.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RAILROADS = ("BNSF", "UP", "NS", "CSX", "CN", "CPKC")
FEATURES = {  # name -> what it tells the model
    "yoy_4w": "YoY growth, trailing 4 weeks (recent momentum)",
    "yoy_13w": "YoY growth, trailing 13 weeks",
    "qtd_yoy": "YoY growth, quarter to date",
    "weeks_remaining": "Weeks left in the quarter",
    "quarter_of_year": "Quarter of the year (seasonality)",
    "holiday_shift": "Christmas / New Year weeks left, vs. the same weeks last year",
    "intermodal_yoy_13w": "Intermodal YoY growth, trailing 13 weeks",
    "coal_yoy_13w": "Coal YoY growth, trailing 13 weeks",
    "merchandise_yoy_13w": "Merchandise YoY growth, trailing 13 weeks",
    "network_yoy_13w": "All railroads' YoY growth, trailing 13 weeks (freight cycle)",
    "speed_yoy_4w": "Train speed vs. last year, trailing 4 weeks",
    "dwell_yoy_4w": "Terminal dwell vs. last year, trailing 4 weeks",
    "cars_online_yoy_4w": "Cars online vs. last year, trailing 4 weeks",
    "railroad": "Railroad",
}


def project(observed, ly_remaining, g):
    return observed + g * ly_remaining


def baseline_growth(rows: pd.DataFrame) -> pd.Series:
    """The seasonal run-rate: the rest of the quarter at this year's level, in earlier years' seasonal shape."""
    return np.exp(rows["base_growth"])


def inputs(rows: pd.DataFrame) -> pd.DataFrame:
    """The feature table the model sees; railroad as a category so it can learn per-railroad behaviour."""
    return rows[list(FEATURES)].assign(railroad=pd.Categorical(rows["railroad"], categories=RAILROADS))


def correction(rows: pd.DataFrame) -> pd.Series:
    """What the model learns: actual remaining-weeks growth minus the baseline's, both as log ratios."""
    return rows["target"] - rows["base_growth"]


def fit(rows: pd.DataFrame) -> HistGradientBoostingRegressor:
    """Learn the correction to the baseline's growth from past checkpoints.

    Small, slow-learning trees: the training set is only a few hundred rows per railroad.
    """
    model = HistGradientBoostingRegressor(learning_rate=0.05, max_iter=200, max_leaf_nodes=15,
                                          min_samples_leaf=20, l2_regularization=1.0,
                                          categorical_features="from_dtype", random_state=0)
    return model.fit(inputs(rows), correction(rows))


def model_growth(model: HistGradientBoostingRegressor, rows: pd.DataFrame) -> pd.Series:
    """The baseline's growth, adjusted by the model's predicted correction."""
    return pd.Series(np.exp(rows["base_growth"] + model.predict(inputs(rows))), index=rows.index)
