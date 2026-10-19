-- Rail freight pipeline schema. Applied on every start; safe to re-run.
--   core: published data the analysis reads (only rows that passed every row check)
--   ops:  pipeline monitoring (job runs, issues, revisions to history)

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ops;

-- Reference data: anything not listed here is held back by the load -------------
CREATE TABLE IF NOT EXISTS core.railroad (
  railroad    text PRIMARY KEY,            -- code used in the source data
  name        text NOT NULL,
  merged_into text REFERENCES core.railroad -- set once a railroad stops filing on its own
);

CREATE TABLE IF NOT EXISTS core.commodity (
  commodity text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS core.measure (
  measure     text PRIMARY KEY,            -- short key used in queries
  source_name text NOT NULL UNIQUE,        -- exact name in the service dataset
  unit        text NOT NULL
);

-- Published data ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.carloads (
  week_ending     date    NOT NULL,        -- Saturday
  submission_date date    NOT NULL,        -- Wednesday filing; join key with service
  railroad        text    NOT NULL REFERENCES core.railroad,
  commodity       text    NOT NULL REFERENCES core.commodity,
  load_type       text    NOT NULL CHECK (load_type IN ('Originated', 'Received')),
  carloads        numeric,                 -- numeric: CPKC reports half cars
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (week_ending, railroad, commodity, load_type)
);

CREATE TABLE IF NOT EXISTS core.service_metric (
  week_ending     date    NOT NULL,        -- Friday
  submission_date date    NOT NULL,
  railroad        text    NOT NULL REFERENCES core.railroad,
  measure         text    NOT NULL REFERENCES core.measure,
  variable        text    NOT NULL,
  subvariable     text    NOT NULL DEFAULT '',  -- '' when blank, so it can be in the key
  value           numeric,                 -- NULL = not reported (never 0)
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (week_ending, railroad, measure, variable, subvariable)
);

-- Monitoring ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops.job_run (
  run_id            serial PRIMARY KEY,
  dataset           text NOT NULL,         -- carloads | service
  status            text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  started_at        timestamptz NOT NULL DEFAULT now(),
  finished_at       timestamptz,
  source_updated_at timestamptz,           -- USDA's rowsUpdatedAt when the run started
  rows_fetched      int,
  rows_changed      int,                   -- inserted or updated in core
  rows_held         int,                   -- failed a row check, not published
  revisions         int,                   -- published values that changed
  error             text
);

CREATE TABLE IF NOT EXISTS ops.issue (
  issue_id    serial PRIMARY KEY,
  run_id      int REFERENCES ops.job_run,  -- NULL for checks outside a load (freshness)
  dataset     text NOT NULL,
  check_name  text NOT NULL,
  action      text NOT NULL CHECK (action IN ('held', 'flagged')),  -- held = row not published
  railroad    text,
  week_ending date,
  detail      text NOT NULL,
  source_row  jsonb,                       -- the row as received, for held rows
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.revision (
  revision_id serial PRIMARY KEY,
  run_id      int NOT NULL REFERENCES ops.job_run,
  dataset     text NOT NULL,
  railroad    text NOT NULL,
  week_ending date NOT NULL,
  series      text NOT NULL,               -- e.g. 'Grain / Originated', 'train_speed / System'
  old_value   numeric,
  new_value   numeric,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Seeds -----------------------------------------------------------------------------
INSERT INTO core.railroad VALUES
  ('BNSF', 'BNSF Railway', NULL),
  ('UP',   'Union Pacific', NULL),
  ('NS',   'Norfolk Southern', NULL),
  ('CSX',  'CSX Transportation', NULL),
  ('CN',   'Canadian National (U.S. operations)', NULL),
  ('CPKC', 'Canadian Pacific Kansas City (U.S. operations)', NULL),
  ('CP',   'Canadian Pacific (U.S. operations)', 'CPKC'),  -- last filed 2025-05-03
  ('KCS',  'Kansas City Southern', 'CPKC')                 -- last filed 2025-05-03
ON CONFLICT DO NOTHING;

INSERT INTO core.commodity VALUES
  ('All Other'), ('Chemicals'), ('Coal'), ('Coke'), ('Containers'),
  ('Crushed Stone, Sand and Gravel'), ('Farm Products except Grain'), ('Fertilizer'),
  ('Food and Kindred Products'), ('Grain'), ('Grain Mill Products'), ('Iron and Steel Scrap'),
  ('Lumber and Wood Products'), ('Metallic Ores'), ('Metals'), ('Motor Vehicles and Equipment'),
  ('Non Metallic Minerals'), ('Petroleum Products'), ('Primary Forest Products'),
  ('Pulp, Paper and Allied Products'), ('Stone, Clay and Glass Products'), ('Trailers'),
  ('Waste and Scrap Materials')
ON CONFLICT DO NOTHING;

-- The service dataset's 'Weekly Carloads By 23 Commodity Categories' is not listed:
-- it duplicates the carloads dataset and is used only for the reconciliation check.
INSERT INTO core.measure VALUES
  ('train_speed',         'Average Train Speed  (MPH)', 'mph'),  -- two spaces in source
  ('terminal_dwell',      'Average Terminal Dwell Time (Excluding Cars on Run Through Trains) (Hours)', 'hours'),
  ('origin_dwell',        'Average Dwell Time at Origin for Unit Train Shipments (Hours)', 'hours'),
  ('cars_online',         'Cars On Line (Count)', 'cars'),
  ('cars_idle_48h',       'Weekly Average Number of Loaded and Empty Cars in Revenue Service That Have Not Moved 48 Hours Or Greater', 'cars'),
  ('trains_held',         'Weekly Average Number of Trains Holding Per Day by Train Type and Cause', 'trains/day'),
  ('grain_cars_loaded',   'Weekly total grain cars loaded and billed, reported by State and Type of Car Ordering System', 'cars/week'),
  ('grain_car_orders',    'Grain Car Order Fulfillment Metrics (Count)', 'cars'),
  ('grain_shuttle_turns', 'Average Grain Shuttle Turns per Month By Region', 'trips/month'),
  ('coal_loadings',       'Coal Unit Train Loadings or Carloadings by Coal Production Region (Count)', 'trains or cars')
ON CONFLICT DO NOTHING;
