# U.S. Rail Freight Data Pipeline

Loads two public USDA AgTransport datasets (weekly railroad filings to the Surface Transportation Board) into Postgres, keeps them current, and checks them before anything is published.

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
| Pipeline logs | `docker compose logs -f worker` |
| Database (pgAdmin) | http://localhost:5050, server **rail**, password `rail` |
| Database (any client) | `postgresql://rail:rail@localhost:5432/rail` |
| Alert emails (Mailpit) | http://localhost:8025 |

The worker loads five years of history on first start (usually ~5 minutes; up to ~20 when the USDA API is slow), then checks hourly for new data.

```bash
docker compose run --rm worker python -m rail load     # load now
docker compose run --rm worker python -m pytest -q     # run the tests
```

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

A held row never overwrites a published one: the last good value stays until the source is fixed.

**Revisions.** When the source changes a value we already published, the new value is published and the change is logged in `ops.revision` (old value, new value). Each run's email lists them by railroad.

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
sql/schema.sql  tables and reference data (railroads, commodities, measures)
tests/          check and load behaviour against a real Postgres
```

## Local development without Docker

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb rail_dev && createdb rail_test
DATABASE_URL=postgresql:///rail_dev .venv/bin/python -m rail load
TEST_DATABASE_URL=postgresql:///rail_test .venv/bin/python -m pytest -q
```
