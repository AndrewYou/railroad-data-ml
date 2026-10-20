# U.S. Rail Freight Monitor

Loads two public USDA AgTransport datasets (weekly railroad filings to the Surface Transportation Board) into Postgres, keeps them current, checks them before anything is published, and shows them on a one-screen dashboard for equity research.

| Dataset | Socrata ID | Rows (from 2017) |
|---|---|---|
| [Rail Carloadings](https://agtransport.usda.gov/Rail/Rail-Carloadings/tb7q-kn5i) | `tb7q-kn5i` | ~157K |
| [STB Railroad Service Metrics](https://agtransport.usda.gov/Rail/STB-Railroad-Service-Metrics/axkm-yjzy) | `axkm-yjzy` | ~1.3M |

How it works, the data checks and the dashboard are described in the [write-up](docs/WRITEUP.pdf).

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

The worker loads the full history (from 2017) on first start (usually ~4 minutes; longer when the USDA API is slow), then checks hourly for new data.

```bash
docker compose run --rm worker python -m rail load       # refresh the last 5 years now
docker compose run --rm worker python -m rail backfill   # reload the full history from 2017
docker compose run --rm worker python -m nowcast         # rerun the carload projection
docker compose run --rm worker python -m pytest -q       # run the tests
```

## Monitoring

Everything is in Postgres, so you can query it in pgAdmin:

```sql
SELECT * FROM ops.job_run ORDER BY run_id DESC;                    -- every run: status, row counts, error
SELECT * FROM ops.issue WHERE run_id = (SELECT max(run_id) FROM ops.job_run);
SELECT * FROM ops.revision ORDER BY revision_id DESC;              -- restated history
```

Nowcast results are in schema `ml` (`ml.run`, `ml.backtest`, `ml.projection`). After each load the worker emails a summary (runs, issues, revisions) to Mailpit. To send real email, point `SMTP_HOST`, `SMTP_PORT` and `ALERT_TO` at a mail server.

## Project layout

```
rail/
  api.py        USDA API: dataset metadata and paged rows
  datasets.py   the two datasets: source fields, keys, and the SQL that cleans a source row
  load.py       stage -> hold -> record revisions -> publish
  checks.py     data checks
  pipeline.py   jobs: load both datasets with run tracking; hourly watcher
  alerts.py     email summary
nowcast/
  features.py   checkpoint rows: what was known at week k of a quarter, and the outcome
  model.py      baseline run-rate, gradient boosting correction, the projection formula
  backtest.py   walk-forward backtest, error metrics, permutation importance
  __main__.py   python -m nowcast: backtest + live projection, written to schema ml
dashboard/
  main.py       entry point: page setup and navigation
  app.py        Equity Research page
  nowcast_page.py  Carload Projection page (+ nowcast_notes.md)
  data.py       queries and comparisons (YoY, quarter to date, drivers, share)
  charts.py     Plotly figures, light and dark palettes
sql/schema.sql  tables and reference data (railroads, commodities, measures)
sql/terminals.sql  terminal coordinates for the map
sql/views.sql   analysis views (mart schema)
sql/nowcast.sql nowcast results (ml schema)
tests/          load, checks and nowcast behaviour against a real Postgres
```

## Local development without Docker

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb rail_dev && createdb rail_test
DATABASE_URL=postgresql:///rail_dev .venv/bin/python -m rail backfill    # first load, then nowcast
TEST_DATABASE_URL=postgresql:///rail_test .venv/bin/python -m pytest -q
DATABASE_URL=postgresql:///rail_dev PYTHONPATH=. .venv/bin/streamlit run dashboard/main.py
```
