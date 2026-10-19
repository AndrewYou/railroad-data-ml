# U.S. Rail Freight Monitor

Loads two public USDA AgTransport datasets (weekly railroad filings to the Surface Transportation Board) into Postgres, keeps them current, checks them before anything is published, and shows them on a one-screen dashboard for equity research.

| Dataset | Socrata ID | Rows since 2021 |
|---|---|---|
| [Rail Carloadings](https://agtransport.usda.gov/Rail/Rail-Carloadings/tb7q-kn5i) | `tb7q-kn5i` | ~94K |
| [STB Railroad Service Metrics](https://agtransport.usda.gov/Rail/STB-Railroad-Service-Metrics/axkm-yjzy) | `axkm-yjzy` | ~890K |

## Quick start

Needs Docker only. No accounts, keys or credentials.

```bash
docker compose up -d --build
```

| What | Where |
|---|---|
| **Dashboard** | http://localhost:8501 |
| Pipeline logs | `docker compose logs -f worker` |
| Database (pgAdmin) | http://localhost:5050, server **rail**, password `rail` |
| Database (any client) | `postgresql://rail:rail@localhost:5432/rail` |
| Alert emails (Mailpit) | http://localhost:8025 |

The worker loads five years of history on first start (usually ~5 minutes; up to ~20 when the USDA API is slow), then checks hourly for new data.

```bash
docker compose run --rm worker python -m rail load     # load now
docker compose run --rm worker python -m pytest -q     # run the tests
```

## Dashboard

"Daniel Plainview's Dashboard": one screen. The top bar picks the railroads and one **trailing window** (the trailing 1, 2 or 4 weeks vs the same weeks a year earlier) that every YoY view uses: the map, drivers, terminals table, and the YoY % modes of volume and service.

| Panel | Question it answers | Toggles |
|---|---|---|
| **Map** | Where is the network congested, and where is grain or coal moving vs last year? | Terminal Dwell (click a terminal to chart it) · Grain Cars Loaded · Grain Car Orders · Grain Shuttle Turns · Coal Loadings. These are the only measures reported by place; the rest are system-wide per railroad |
| **What's moving** | Weekly originated carloads, and YoY % over the comparison window | Carloads / YoY % · Network / Segment / Railroad · 1Y / 2Y / 5Y (how far back) |
| **What's driving it** | Waterfall over the comparison window. Each commodity's, railroad's or segment's change in points of the network's YoY %, stepping from 0 to the network total | Commodity / Railroad / Segment |
| **Service** | Is service improving? Each railroad vs its own history only | Vs. History (one railroad) / YoY % (All) · Speed / Dwell / Cars Online |
| **Market share** | Share between direct competitors (UP vs BNSF in the West, CSX vs NS in the East), or of the whole network | All Railroads / West / East · Segment · Commodity |
| **Tables** | Quarter-to-date tracker with projection (formula in the column tooltip), commodities, terminals | Quarter picker · sort by clicking a column; search from the table toolbar |

- **Export.** *Excel* (top bar) downloads every table plus the data behind each chart, with an About sheet recording the data week, load time and filters, so saved snapshots are self-describing. Each chart's camera icon saves a 3x PNG for decks; each table's toolbar downloads CSV.
- **Light / dark.** ⋮ menu → Settings → Theme. Charts follow the app theme.
- **Conventions.** Volume is Originated carloads only. CPKC is one series across the 2025 merger (CP + KCS before it), and so are its terminals. YoY compares to the same weeks 52 weeks earlier. Service levels are never compared across railroads.
- **Logic** lives in SQL views (`sql/views.sql`, schema `mart`), so an analyst in pgAdmin gets the same numbers as the dashboard.

## How it works

```
USDA API ──► stage (temp table, as received) ──► row checks ──► publish to core ──► dataset checks ──► email summary
                                                    │                                     │
                                                    └──► ops.issue (held rows) ◄───────────┘ (flagged)
```

- **When it runs.** Every hour the worker reads each dataset's `rowsUpdatedAt` from the API metadata (one small request). If it's newer than our last successful load, it loads. Railroads file on Wednesday and USDA republishes Thursday morning, so new data lands within an hour. As a backstop it loads anyway if nothing has succeeded in 7 days.
- **What it fetches.** Every load re-fetches the full window: January 1 five years ago to today (currently 2021-01-01 onward). That picks up restatements of any age, and the first load and the weekly refresh are the same code.
- **How it publishes.** One transaction per dataset. Rows are inserted or updated, never deleted, so a truncated API response can't wipe history. If anything errors, the transaction rolls back and the published data is unchanged.

## Data checks

Each check answers: *would an analyst be misled by what we publish?* Code: [rail/checks.py](rail/checks.py).

| Check | Level | If it fails |
|---|---|---|
| `invalid_row`: unknown railroad, commodity or measure, or a missing field | row | Row held back; add the new code to `sql/schema.sql` to release it |
| `duplicate_key`: two source rows for the same series and week | row | Both held back |
| `incomplete_week`: an active railroad is missing commodities or headline service metrics (speed, dwell, cars online) in the latest week | dataset | Flagged |
| `carloads_mismatch`: a railroad's weekly carloads differ between the two datasets | dataset | Flagged |
| `removed_upstream`: a published row is no longer in the source | dataset | Kept and flagged |
| `stale_data`: no new filing by Friday noon ET | dataset | Flagged and emailed once |
| `unmapped_terminal`: a reported terminal has no map coordinates | dataset | Flagged; add it to `sql/terminals.sql` |

Revisions are in `ops.revision` and each run's email. A held row never overwrites a published one: the last good value stays until the source is fixed.

**Revisions.** When the source changes a value we already published, the new value is published and the change is logged in `ops.revision` (old value, new value). Each run's email lists them by railroad.

## What breaks a load, and what happens

| What goes wrong | Example | What happens | Published data | How to fix |
|---|---|---|---|---|
| API down or times out | USDA outage | Each request retried 5 times with backoff. Mid-load: the run fails (`ops.job_run.status = 'failed'`) and an email goes out. During the hourly check: logged, retried next hour, and `stale_data` emails if it lasts past Friday noon | Unchanged | Nothing; the watcher retries next hour |
| Value can't be parsed | `"n/a"` in a number field | The dataset's transaction rolls back; run fails with the error; email sent | Unchanged | Fix the parse rule in `rail/datasets.py` |
| New railroad, commodity or measure | Merged railroad files as `UPNS`; a measure is renamed | Those rows held (`invalid_row`); everything else publishes; listed in every run's email until mapped | Last good values kept; new series missing | Add the code to `sql/schema.sql`, restart the worker; held rows publish on the next load |
| Duplicate rows in the source | Same railroad, commodity and week twice | Both held (`duplicate_key`) | Last good value kept | Usually fixed upstream; released automatically next load |
| Railroad missing from the latest week | NS didn't file | Flagged (`incomplete_week`) | That railroad's week is absent, not zero | Wait for the filing, or ask USDA |
| The two datasets disagree | Carloads total ≠ copy in service data | Flagged (`carloads_mismatch`) | Carloads dataset published as-is | Investigate which source is wrong |
| Row vanishes upstream | USDA drops a week | Flagged (`removed_upstream`) | Our copy kept | Investigate; delete by hand if it was wrong |
| Filing is late | Nothing new by Friday noon ET | Flagged once (`stale_data`), email sent | Last week's data | Usually USDA delay, e.g. holidays |
| Database down | Container stopped | Run fails before publishing; watcher logs and retries hourly | Unchanged | Restart Postgres |

## Monitoring

Everything is in Postgres, so you can query it in pgAdmin:

```sql
SELECT * FROM ops.job_run ORDER BY run_id DESC;                    -- every run: status, row counts, error
SELECT * FROM ops.issue WHERE run_id = (SELECT max(run_id) FROM ops.job_run);
SELECT * FROM ops.revision ORDER BY revision_id DESC;              -- restated history
```

After each load the worker emails a summary (runs, issues, revisions) to Mailpit. To send real email, point `SMTP_HOST`, `SMTP_PORT` and `ALERT_TO` at a mail server.

## Project layout

```
rail/
  api.py        USDA API: dataset metadata and paged rows
  datasets.py   the two datasets: source fields, keys, and the SQL that cleans a source row
  load.py       stage -> hold -> record revisions -> publish
  checks.py     data checks
  pipeline.py   jobs: load both datasets with run tracking; hourly watcher
  alerts.py     email summary
dashboard/
  app.py        layout and toggles
  data.py       queries and comparisons (YoY, quarter to date, drivers, share)
  charts.py     Plotly figures, light and dark palettes
sql/schema.sql  tables and reference data (railroads, commodities, measures)
sql/terminals.sql  terminal coordinates for the map
sql/views.sql   analysis views (mart schema)
tests/          check and load behaviour against a real Postgres
```

## Local development without Docker

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb rail_dev && createdb rail_test
DATABASE_URL=postgresql:///rail_dev .venv/bin/python -m rail load
TEST_DATABASE_URL=postgresql:///rail_test .venv/bin/python -m pytest -q
DATABASE_URL=postgresql:///rail_dev PYTHONPATH=. .venv/bin/streamlit run dashboard/app.py
```
