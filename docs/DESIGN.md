# Design notes

Data-model decisions and the reasoning behind them. Pipeline and checks: see README.

## Why one table with a railroad column, not a table per railroad
Cross-railroad queries stay a single `WHERE`/`GROUP BY` instead of a 6-way `UNION`. A merger (CP+KCS → CPKC, or a future UP+NS) becomes a row in `core.railroad` with `merged_into` set, not new tables.

## Why long format
Both sources are already long (measure / variable / subvariable / value). Service metrics have dozens of variants (speed by 9 train types, dwell at 88 terminals, trains held by type × cause, grain by 51 states). A wide table would be mostly empty, and every new variant would need a schema change. In long format, a new metric is one row in `core.measure`.

## Layers
- **core**: typed, primary-keyed, upserted. Only rows that passed every row check.
- **ops**: job runs, issues (held or flagged rows) and revisions to history.
- No raw layer: held rows keep their source JSON in `ops.issue`, and the API can always be re-read. It would also double storage.

## Refresh
Every run re-fetches the whole window (Jan 1 five years ago onward) from the API and upserts. Nothing is deleted, so a truncated response can't wipe history; rows that vanish upstream are flagged instead. Changed values are logged to `ops.revision`. The first load and the weekly refresh are the same job.

## Measures (`core.measure`)
- Each measure has a short key (`train_speed`), the exact source name, and a `unit` (the source has none; units come from the measure names and STB definitions).
- Kinds of measure, which decide how they combine:
  - flows (carloads, grain cars loaded): counted per week, so they add up.
  - stocks (cars online, cars idle 48h+): point-in-time counts; add across railroads, not across weeks.
  - averages (speed, dwell, shuttle turns): never add.
- Stitching CP+KCS into CPKC: flows and stocks sum, averages break. Received carloads also break; see CLAUDE.md.

## Analysis conventions
- Volume = Originated only.
- Service comparisons are railroad vs its own history: YoY by ISO week, vs trailing 13-week average, or z-score vs a 3-year baseline.
- Raw levels across railroads are shown only with a methodology caveat.
- Holiday weeks (Christmas/New Year, Thanksgiving) are flagged and drawn as markers.
- CPKC YoY: carloads use the pro-forma CP+KCS sum. Speed and dwell have their own year-ago history only from May 2026 on, so earlier weeks show n/a.

## Profiling snapshot (data through week ending 2026-10-10)
13 weeks vs the same 13 weeks a year earlier, originated carloads:
- **By railroad:** BNSF +3.2%, UP +7.0%, NS +2.2%, CSX +2.9%, CN −1.4%, CPKC +4.7% (vs CP+KCS).
- **By commodity:** containers +5.3%, grain +7.5%, coal −3.6%, motor vehicles −3.8%.

Five-year system averages (methodology differs, so do not compare across railroads):
- **Dwell:** CN 16.1 h … BNSF 24.7 h.
- **Speed:** NS 20.7 mph … KCS 26.5 mph.

## Open items
- A UP–NS merger would arrive as an unknown railroad code (held by `invalid_row`), then be mapped with `merged_into`. The same stitching rules apply.

## Sources
- Rail Carloadings: https://agtransport.usda.gov/Rail/Rail-Carloadings/tb7q-kn5i
- STB Railroad Service Metrics: https://agtransport.usda.gov/Rail/STB-Railroad-Service-Metrics/axkm-yjzy
- STB Rail Service Data (methodologies, change notes): https://www.stb.gov/reports-data/rail-service-data/
