"""Carload Nowcast (Experiment): each railroad's projected quarter of originated carloads, and how the
baseline and the model have done in a walk-forward backtest. Results come from `python -m nowcast` (schema ml).
"""
from pathlib import Path

import pandas as pd
import streamlit as st

import charts
import data
from nowcast.features import quarter_weeks

CHART_H = 260
METHODS = ["baseline", "model"]
SHORT = {"baseline": "Baseline", "model": "Model v2"}
NOTES = Path(__file__).with_name("nowcast_notes.md")

# Recorded during development (Oct 19, 2026): mean error on the same 15 test quarters, 2023 Q1 - 2026 Q3.
# Baseline v2 recorded Oct 29, 2026.
EXPERIMENTS = pd.DataFrame({"error": [1.75, 2.13, 2.09, 1.93, 1.62, 1.80]}, index=[
    "Baseline v1: 13-week run-rate, last year's shape",
    "Model v1: gradient boosting, predicts growth",
    "Model v2: gradient boosting, corrects baseline",
    "Model v2, history from 2017",
    "Baseline v2: 3-year seasonal shape, COVID skipped (in use)",
    "Model v2 on Baseline v2"])
LONGER_HISTORY = pd.DataFrame({  # history from 2017, 30 test quarters (2019 Q2 - 2026 Q3)
    "Test period": ["All 30 quarters", "Excluding COVID (2020 - mid-2021)", "2020 only",
                    "0 weeks reported (all 30 quarters)"],
    "Baseline v1": ["2.35%", "1.94%", "4.30%", "4.82%"],
    "Model v2 on v1": ["2.48%", "2.07%", "4.10%", "4.52%"],
    "Baseline v2": ["1.92%", "1.60%", "4.10%", "3.85%"],
    "Model v2 on v2": ["2.13%", "1.80%", "3.95%", "3.97%"]})


def panel_title(text: str) -> None:
    st.markdown(f"**{text}**")


def quarter_name(q: str) -> str:
    return f"{q[:4]} Q{q[-1]}"


run = data.nowcast_run() if data.data_version() else None
if run is None:
    st.info("The projection runs after the first data load (a few minutes after `docker compose up`). Refresh shortly.")
    st.stop()

backtest, projection = data.nowcast_backtest(), data.nowcast_projection()
errors = data.backtest_errors(backtest)
winner = run["winner"]
other = "model" if winner == "baseline" else "baseline"
overall = errors[METHODS].mean()
first, test_from, test_to = (quarter_name(run[c]) for c in ("first_quarter", "test_from", "test_to"))

title, pick_col, status_col = st.columns([3.4, 1.4, 4.2], vertical_alignment="center")
title.markdown("<div style='font-size:1.6rem;font-weight:700;line-height:1.2;margin-bottom:1rem'>"
               "Quarterly Carload Projection (Experiment)</div>", unsafe_allow_html=True)
railroad = pick_col.selectbox("Railroad", ["All Railroads", *charts.RAILROADS], label_visibility="collapsed")
trained = pd.Timestamp(run["trained_at"]).tz_convert("America/New_York")
status_col.markdown(
    f"<div style='font-size:0.78rem;line-height:1.35;margin-bottom:1rem'>Projects each railroad's quarterly total of "
    f"<b>originated carloads</b> (volume, not service metrics) before the quarter ends.<br>"
    f"Trained {trained:%a %b} {trained.day}, {trained.year} {trained:%-I:%M %p} ET</div>", unsafe_allow_html=True)


def scope(df: pd.DataFrame) -> pd.DataFrame:
    return df if railroad == "All Railroads" else df[df["railroad"] == railroad]


# This quarter, and the conclusion: the point of the experiment -----------------------------

live = scope(projection)
totals = live.groupby("method")[["projection", "low", "high", "last_year"]].sum()  # railroads add up
quarter, k = live["quarter"].iloc[0], int(live["checkpoint"].max())
typical = errors[errors["checkpoint"] == k][winner].mean()


def yoy(method: str) -> float:
    return (totals.loc[method, "projection"] / totals.loc[method, "last_year"] - 1) * 100


st.info(f"**The {SHORT[winner].lower()} is in use** because it had the lower average error over "
        f"{run['test_quarters']} backtest quarters ({overall[winner]:.2f}% vs. {overall[other]:.2f}% for "
        f"{SHORT[other]}).", icon="📌")

with st.container(border=True):
    panel_title(f"{railroad}: {quarter_name(quarter)} Originated Carloads, Projected")
    tiles = st.columns(4)
    tiles[0].metric(f"Projection ({SHORT[winner]}, in Use)", f"{totals.loc[winner, 'projection']:,.0f}",
                    delta=f"{yoy(winner):+.1f}% YoY",
                    help=f"Same quarter last year: {totals.loc[winner, 'last_year']:,.0f} carloads.")
    tiles[1].metric("Typical Range", f"± {typical:.1f}%",
                    help=f"{totals.loc[winner, 'low']:,.0f} to {totals.loc[winner, 'high']:,.0f} carloads. In past "
                         f"quarters, the {SHORT[winner].lower()}'s projection with {k} week{'s' if k != 1 else ''} "
                         f"reported missed the actual total by {typical:.1f}% on average.")
    tiles[2].metric(f"Projection ({SHORT[other]})", f"{totals.loc[other, 'projection']:,.0f}",
                    delta=f"{yoy(other):+.1f}% YoY")
    tiles[3].metric(f"Weeks Reported in {quarter_name(quarter)}", f"{k} of {len(quarter_weeks(pd.Period(quarter)))}")


# How it's calculated: the two methods side by side ----------------------------------------

with st.container(border=True):
    panel_title("How It's Calculated: Baseline vs. Model")
    baseline_col, model_col, feature_col = st.columns([1, 1, 1.15])
    with baseline_col, st.container(border=True):
        st.markdown("**Baseline: Seasonal Run-Rate (No ML)**")
        st.latex(r"\text{Projection} = \text{Reported} + \text{Expected}")
        st.latex(r"\text{Expected} = \operatorname{median}_{y}\Big(\text{Remaining}_{y} \times "
                 r"\frac{\text{last 13 weeks}}{\text{same 13 weeks } y \text{ years earlier}}\Big)")
        st.markdown("*Reported* = carloads in the weeks already reported. *Remaining (y)* = the same remaining "
                    "weeks *y* years earlier, for up to 3 earlier years, skipping any that touch the 2020 COVID "
                    "collapse. The rest of the quarter runs at this year's level in the usual seasonal shape, "
                    "and the median keeps one unusual year from setting that shape. No training needed.")
    with model_col, st.container(border=True):
        st.markdown("**Model v2: Gradient Boosting, Correcting the Baseline**")
        st.latex(r"\text{Projection} = \text{Reported} + e^{\,\hat{c}} \times \text{Expected}")
        st.markdown("*ĉ* is a correction predicted by **gradient boosting**: many small decision trees, each "
                    "fixing the errors of the ones before, learned from the features on the right. It starts from "
                    "the baseline, so with weak evidence it stays close to it. It replaced Model v1, gradient "
                    "boosting predicting growth directly (see Experiments).")
    with feature_col:
        features = data.feature_importance().query("importance > 0")  # hide features that didn't help
        features = features.assign(share=features["importance"] / features["importance"].max() * 100)
        st.dataframe(features[["description", "share"]], hide_index=True, height=(len(features) + 1) * 35 + 3,
                     column_config={
            "description": st.column_config.TextColumn("Model Feature"),
            "share": st.column_config.ProgressColumn(
                "Importance", min_value=0, max_value=100, format="%.0f%%",
                help="Permutation importance: shuffle one feature and measure how much worse the model gets, "
                     "relative to the most useful feature.")})
        st.caption("Features that didn't improve the model are not shown.")
    st.markdown(
        f"- **Training data:** **{first} to {test_to}**, {run['train_quarters']} quarters. The carloads data starts "
        f"in March 2017, and every comparison needs the same weeks a year earlier, so {first} is the first quarter "
        f"that can be compared.\n"
        f"- **Backtest:** each quarter from **{test_from} to {test_to}** ({run['test_quarters']} quarters) is "
        f"projected at every week by a model trained only on the quarters before it: {test_from} learns from "
        f"{first} onward (4 quarters), {test_to} from {first} to the quarter before it. "
        f"This quarter's projection uses all {run['train_quarters']}.\n"
        f"- **Winner:** the lower average backtest error. Now: **{SHORT[winner]}, {overall[winner]:.2f}%** vs. "
        f"{SHORT[other]}, {overall[other]:.2f}%.")


# Projections vs actuals -----------------------------------------------------------------

with st.container(border=True):
    title_col, slider_col = st.columns([1.2, 2], vertical_alignment="center")
    title_col.markdown(f"**Projections vs. Actuals, {test_from} to {test_to}**")
    at_week = slider_col.select_slider("Weeks reported", options=list(range(13)), value=0,
                                       format_func=lambda w: f"{w} Weeks Reported", label_visibility="collapsed")
    history = (scope(backtest).query("checkpoint == @at_week")
               .groupby("quarter")[["actual", *METHODS]].sum().reset_index())
    st.plotly_chart(charts.projections_vs_actuals(history, CHART_H),
                    config=charts.export_config(f"nowcast_projections_{at_week}w"))
    st.caption("The slider sets how many weeks of each past quarter had been reported when the projection was made. "
               "At 0 it is a pure forecast, made before the quarter started; by 12 most of the quarter is known, so "
               "both lines converge on the actual.")


# Error: baseline vs Model v2 -------------------------------------------------------------

by_quarter_col, by_railroad_col = st.columns(2)
with by_quarter_col, st.container(border=True):
    panel_title("Error by Quarter")
    by_quarter = scope(errors).groupby("quarter")[METHODS].mean()
    st.plotly_chart(charts.error_bars(by_quarter, CHART_H), config=charts.export_config("nowcast_error_by_quarter"))
    closer = (by_quarter["model"] < by_quarter["baseline"]).sum()
    st.caption(f"Averaged over every week of each quarter. Model v2 was closer in {closer} of {len(by_quarter)}.")

with by_railroad_col, st.container(border=True):
    panel_title("Error by Railroad")
    by_railroad = errors.groupby("railroad")[METHODS].mean().reindex(charts.RAILROADS)
    st.plotly_chart(charts.error_bars(by_railroad, CHART_H), config=charts.export_config("nowcast_error_by_railroad"))
    st.caption("Mean error across every backtest projection, all railroads.")


# Experiments: how the methods compared as the model changed and saw more history -----------

with st.container(border=True):
    panel_title("Experiments: Mean Error on the Same 15 Quarters (2023 Q1 to 2026 Q3)")
    chart_col, table_col = st.columns([1.3, 1])
    with chart_col:
        st.plotly_chart(charts.experiment_bars(EXPERIMENTS, 200), config=charts.export_config("nowcast_experiments"))
    with table_col:
        st.markdown("**Baselines and Model v2 across Different Time Periods**")
        st.dataframe(LONGER_HISTORY, hide_index=True)
    st.markdown(NOTES.read_text())
