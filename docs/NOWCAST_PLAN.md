# Quarter volume nowcast: plan

An experiment: project each railroad's quarterly originated carloads before the quarter ends,
and show honestly whether a machine-learning model beats a simple baseline.
If it doesn't, the dashboard uses the baseline.

## Decisions

| Topic | Decision |
|---|---|
| Target | Quarter total of **originated** carloads per railroad (BNSF, UP, NS, CSX, CN, CPKC). CP+KCS are already stitched into CPKC by `mart.originated`. Segments are future work. |
| Actuals | Sum of the weekly data in this dataset. No hand-entered 10-Q volumes. |
| Quarter of a week | The calendar quarter containing the week's midpoint (`week_ending - 3 days`). Quarters have 13 or 14 weeks. |
| Model | Gradient boosting only (scikit-learn `HistGradientBoostingRegressor`). |
| Winner rule | Lower average backtest error wins. Decided on the backtest only, never on the live quarter. |
| Placement | A separate dashboard page. The equity research screen is unchanged. |

## Method

### One formula, two growth rates

```
projection = Σ actual(w)              for weeks w already reported this quarter
           + g × Σ actual(w − 364d)   for weeks w still to come (same weeks last year)
```

- **Baseline:** `g` = YoY ratio of the trailing 13 weeks
  (`Σ last 13 weeks / Σ same 13 weeks a year earlier`). This is the analyst's run-rate shortcut.
- **Model:** predicts `g` for the remaining weeks. The training target is
  `log(Σ remaining weeks / Σ same weeks last year)`. Using log makes growth and decline symmetric.
- **Revision (after the first backtest):** the model now predicts the *correction* to the baseline,
  `target − log(baseline g)`, and `g = baseline g × exp(correction)`. The baseline was already very good
  (1.75% mean error); learning growth from scratch did worse (2.13%) because ~15 training quarters is
  too little to relearn the run-rate. Starting from the baseline keeps the model close to it when the
  evidence is weak. This was the one planned change; we accept its result rather than keep tuning on
  the same backtest.
- **Revision (history):** the pipeline's first load now backfills from 2017 (refreshes still re-fetch 5 years),
  so the nowcast trains on 2018 Q2 onward and backtests 30 quarters (2019 Q2 – 2026 Q3): baseline 2.35%,
  model 2.48%. The baseline still wins.

The model's only job is to predict a better growth rate than the run-rate. Both methods share
the rest of the formula, so the comparison is fair. The 364-day offset keeps weekdays aligned,
lines up most holidays, and handles 14-week quarters (each week has its own prior-year match).

### Training rows

One row per (railroad, quarter, checkpoint *k*), where *k* = weeks of the quarter already
reported (0 through 12). Every feature uses data up to week *k* only.

### Features

| Feature | Why |
|---|---|
| YoY log ratio, trailing 4 weeks | Recent momentum |
| YoY log ratio, trailing 13 weeks | The baseline's own signal |
| YoY log ratio, quarter to date (NaN at *k* = 0) | What this quarter has done so far |
| Weeks remaining | Fewer weeks left means less to forecast |
| Quarter of year (1–4) | Seasonal patterns in growth |
| Holiday weeks remaining | Christmas/New Year shift between years |
| Segment YoY, trailing 13 weeks (Intermodal, Coal, Merchandise) | Mix: e.g. coal falling while intermodal grows |
| Network YoY, trailing 13 weeks (all railroads) | Macro freight cycle |
| Railroad (categorical) | Lets the model learn railroad-specific behaviour |
| Train speed, terminal dwell, cars online: trailing 4 weeks vs. same weeks last year | Does service predict volume? Each railroad is compared only to itself. NaN for CPKC until 52 weeks after the May 2025 merger, because there is no valid prior year. Gradient boosting handles NaN natively. |

### Backtest (walk-forward)

- For each test quarter Q, train on rows from quarters that ended **before Q started**, then
  project Q at every checkpoint.
- Testing starts once at least 4 training quarters exist. Features need a year of history and the
  window starts Jan 2021, so expect roughly 2022–23 onward: about 15 quarters × 6 railroads.
- Error = `|projection − actual| / actual` for the quarter total.
- Report: mean error overall, by checkpoint, and by railroad, for baseline and model.
- **Explainability:** permutation importance (how much error rises when one feature is shuffled)
  on the backtest predictions.

### Live projection

The current quarter's projection from the winning method, with a typical error range taken from
backtest error at the same checkpoint. Each run also stores its live projection, so over time a
true out-of-sample track record builds up next to the backtest.

### Known limits (state in the write-up)

- The backtest uses today's restated data, not what was known at the time (`ops.revision` could
  rebuild vintages later).
- ~15 test quarters is a small sample, so a small win may be luck. The page says so.
- These are dataset volumes, not reported earnings volumes, so definitions may differ from 10-Qs.

## Build

### Code: `nowcast/` package (pandas + scikit-learn; `rail/` stays psycopg + requests)

| File | Contents |
|---|---|
| `nowcast/features.py` | Load weekly originated + service headline from `mart`; assign quarters; build checkpoint rows and the target. |
| `nowcast/model.py` | `baseline_growth(...)`, model fit/predict, `project(observed, last_year_remaining, g)`. |
| `nowcast/backtest.py` | Walk-forward loop, error metrics, permutation importance, winner choice. |
| `nowcast/__main__.py` | `python -m nowcast`: run the backtest and live projection, write to the `ml` schema. |

### Storage: `sql/nowcast.sql`, schema `ml`

| Table | Rows | Refresh |
|---|---|---|
| `ml.backtest` | railroad, quarter, checkpoint, actual, baseline projection, model projection | replaced each run |
| `ml.metric` | method, checkpoint, railroad (or all), mean abs % error | replaced each run |
| `ml.feature_importance` | feature, description, importance | replaced each run |
| `ml.projection` | run date, railroad, quarter, checkpoint, method, projection, low, high | **append only** (the live track record) |
| `ml.run` | run id, trained at, data version, winner, train/test quarter counts | append only |

### Scheduling

The worker runs the nowcast after each successful load. A failure is logged and emailed, but it
never fails the data load.

### Dashboard

- A new entry point uses `st.navigation` with two pages:
  - **Equity Research**: the current `app.py`, unchanged apart from moving `set_page_config`.
  - **Nowcast (experiment)**: `dashboard/nowcast.py`.
- Nowcast page, with a railroad picker:
  1. **Headline:** current-quarter projection ± typical error, method in use and why, YoY %.
  2. **Projections vs. actuals (line chart):** x = quarter; lines for actual, baseline projection
     and model projection. A "weeks into quarter" slider picks the checkpoint.
  3. **Error by week (line chart):** x = weeks into the quarter; y = mean % error for baseline and
     model. Both fall toward 0 by the last week; the lower line wins.
  4. **How it's calculated:** the formula (`st.latex`), the baseline `g` definition, the backtest
     setup in plain words, and a feature table with descriptions and importance bars.
- Follows the existing light/dark theming (`charts.set_theme`).
- `docker-compose.yml` dashboard command points at the new entry point.

### Tests (`tests/test_nowcast.py`)

- Baseline formula on a small hand-built series gives the hand-calculated answer.
- No leakage: changing any data after checkpoint *k* leaves the features at *k* unchanged.
- Walk-forward never trains on the quarter being tested.
- Quarter assignment, including a week straddling a quarter boundary and a 14-week quarter.

### Docs

- README: "Quarter nowcast (experiment)" section covering what it does, how to run it, and how to
  read the page.
- `docs/DESIGN.md`: the method, the winner rule and the known limits above.
- `requirements.txt`: add `scikit-learn`.

## Order of work

1. Features + baseline + tests. The baseline alone is already a usable projection.
2. Model + walk-forward backtest + metrics. **Checkpoint:** compare the numbers before building any UI.
3. `ml` schema + `python -m nowcast` + worker hook.
4. Dashboard navigation + Nowcast page.
5. README / DESIGN notes.
