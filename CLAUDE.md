# Rail freight data pipeline: project context

Case study: ingest two public USDA AgTransport rail datasets (sourced from STB EP 724 weekly filings) into Postgres, keep them refreshed weekly, and build analysis on top. Requirements: free/no API keys, reproducible from a fresh clone, 5+ years of history.

Full design notes: `docs/DESIGN.md`. Schema: `sql/schema.sql`. Pipeline: `rail/` (see README).

## Pipeline decisions (agreed with the user)
- Code style: clean, simple, concise. Reviewers have 1-2 hours. No frameworks beyond psycopg + requests.
- Fetch from the Socrata **API** (JSON, paged 50K), never file downloads. Window = Jan 1 five years ago → today.
- Every load re-fetches the whole window. Insert/update only, never delete.
- Hourly watcher compares API metadata `rowsUpdatedAt` to the last successful run; 7-day backstop.
- Checks are row-level where possible: failing rows are held back (`ops.issue`, action `held`) and never overwrite a published value. Dataset-level problems are flagged. Check list lives in `rail/checks.py` and README.
- Restatements are recorded in `ops.revision` and summarised in the run email.
- Alerts: email via SMTP to Mailpit (local, no credentials). Everything runs from `docker compose up`.
- Skipped for now (note in write-up as future work): volume-swing bounds, share-of-network bounds, service value range checks. No composite "service scorecard" (user: too black-box for investors).

## Sources (Socrata, no key needed)
| Dataset | ID | Rows | Cols | History | Week ends |
|---|---|---|---|---|---|
| Rail Carloadings | `tb7q-kn5i` | ~157K | 9 | 2017-03-25 → | Saturday |
| STB Railroad Service Metrics | `axkm-yjzy` | ~1.59M | 10 | 2014-10-17 → | Friday |

- Full export: `https://agtransport.usda.gov/api/views/<id>/rows.csv?accessType=DOWNLOAD`
- API (used by the pipeline): `https://agtransport.usda.gov/resource/<id>.json?$where=date>='YYYY-MM-DD'&$order=:id&$limit=50000&$offset=N`
- Metadata (`rowsUpdatedAt`): `https://agtransport.usda.gov/api/views/<id>.json`
- Both are filed Wednesdays (`submission_date`) and republished by USDA about a day later.

## Rules that must hold in code
1. **Join the two datasets on `submission_date`** (or a reporting-week key derived from it), never on week-ending date. Carloads end Saturday, service ends Friday.
2. **Load carloads only from `tb7q-kn5i`.** Drop measure `Weekly Carloads By 23 Commodity Categories` from the service load (it duplicates it; 157,226 of 157,228 values match).
3. **Network volume = `type = 'Originated'` only.** Received double-counts interchanged cars.
4. **Blank values load as NULL, never 0.** About 11.2K service values are blank. Zero carloads (4,569 rows) are real zeros.
5. **`carloads` is numeric, not int.** CPKC has half-car values (e.g. 258.5 for the week ending 2026-01-24).
6. **Store `subvariable` as `''` when blank**, so it can sit in the primary key.
7. **Refresh = re-pull the whole 5-year window and upsert (never delete).** Railroads restate past weeks. Backfill and refresh share one code path.
8. **Drop `comparable_week_this_year`.** It is a USDA charting helper.
9. **Never compare service levels across railroads.** Compare each railroad to its own history (YoY, vs trailing average, z-score).
10. **Never sum or average `average`-type measures across railroads** (speed, dwell). `measure.agg_type` enforces this.

## Railroads
Codes in data: BNSF, UP, NS, CSX, CN, CP, KCS, CPKC.
- CP and KCS last week: 2025-05-03 (carloads) / 2025-05-02 (service).
- CPKC first week: 2025-05-10 (carloads) / 2025-05-09 (service).
- CN and CPKC report U.S. operations only.

## CP + KCS → CPKC stitching (follows `measure.agg_type`; build in the analysis layer)
| Kind | Examples | Rule | Evidence at the switch |
|---|---|---|---|
| Flow | originated carloads, grain cars loaded, car orders | sum CP+KCS before, CPKC after | 15,841 → 16,315 |
| Flow across the seam | received carloads | break, do not stitch | 17,594 → 8,654 (CP↔KCS interchange became internal) |
| Stock | cars online, cars idle 48h+ | sum, flag the date | 55,224 → 59,455 (+8% in one week) |
| Average | train speed, terminal/origin dwell | break; CPKC is a new series | CP 21.7 / KCS 25.9 mph → CPKC 20.0 |

Terminal dwell is keyed by cleaned terminal name, so yards shared by CP and CPKC (Bensenville, Harvey…) stay continuous.

## Known data quirks
- System-level speed (`variable='System'`) and dwell (`'System Average'`) only start 2017-03-24. Before that only terminals were reported.
- Inside the 2021+ window, labels are consistent *within* each railroad, so the load does no label cleaning. Variants only differ *between* railroads (CN/NS terminals UPPERCASE; `Uinta basin` vs `Uinta Basin`). Normalize in analysis if comparing labels across railroads.
- Pre-2021 only (outside the window): CP terminal names UPPERCASE through 2017-03-17; system speed/dwell start 2017-03-24.
- Label variants: `Uinta basin`/`Uinta Basin`; `PNW`/`Pacific North West`; chemicals in the 48h+ measure: CN uses `Chemical or Plastics`, others use `Chemical or Allied Products`, CPKC uses neither.
- Partial coverage: coal by region has no KCS/CPKC; grain shuttle turns only BNSF, CP/CPKC, CSX, UP; CN has no Automotive train type; CPKC has no `Other` train speed.
- Blank-heavy (last 5 yrs): CPKC origin dwell 225/450, CSX trains holding 789/6,312, KCS terminal dwell 564/2,632.
- The five lowest weeks of the last five years are all Christmas/New Year weeks. Compare by week of year and flag holidays.
- Week numbering in carloads: week 1 = first week ending on or after Jan 4 (ISO-like). Some years have 53 weeks.
- Coal measure is "unit train loadings *or* carloads", so the unit may differ by railroad.

## Verified against a real Postgres 16 load (Oct 2026)
- Profiling load: all 157,228 carload rows load against the keys with no conflicts; no duplicate service keys since 2021.
- Carload week = submission − 4 days, service week = submission − 5 days.
- Stitching views (CP+KCS → CPKC, driven by `measure.agg_type`) were dropped from schema.sql during the trim; rebuild them in the analysis layer.
