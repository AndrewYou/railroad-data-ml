-- Quarter nowcast (experiment), written by `python -m nowcast` after each data load.
-- backtest / metric / feature_importance are replaced each run; run and projection are append-only,
-- so the live projections build up a true out-of-sample track record over time.
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.run (
  run_id         serial PRIMARY KEY,
  trained_at     timestamptz NOT NULL DEFAULT now(),
  data_version   int,                     -- latest successful ops.job_run when it ran
  winner         text NOT NULL CHECK (winner IN ('baseline', 'model')),
  train_quarters int NOT NULL,            -- complete quarters available to the final model
  test_quarters  int NOT NULL,            -- quarters in the walk-forward backtest
  first_quarter  text NOT NULL,           -- first complete quarter with a year of history (training starts here)
  test_from      text NOT NULL,           -- first backtest quarter (needs 4 earlier quarters to train on)
  test_to        text NOT NULL            -- last backtest quarter = last complete quarter
);

CREATE TABLE IF NOT EXISTS ml.backtest (  -- one walk-forward projection per railroad, quarter and week
  railroad   text NOT NULL,
  quarter    text NOT NULL,               -- e.g. 2026Q3
  checkpoint int  NOT NULL,               -- weeks of the quarter already reported
  actual     numeric NOT NULL,
  baseline   numeric NOT NULL,
  model      numeric NOT NULL,
  PRIMARY KEY (railroad, quarter, checkpoint)
);

CREATE TABLE IF NOT EXISTS ml.metric (    -- mean absolute % error of the quarter total
  scope    text NOT NULL CHECK (scope IN ('overall', 'checkpoint', 'railroad', 'quarter')),
  key      text NOT NULL,                 -- 'all', a checkpoint number, a railroad or a quarter
  baseline numeric NOT NULL,
  model    numeric NOT NULL,
  PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS ml.feature_importance (
  feature     text PRIMARY KEY,
  description text NOT NULL,
  importance  numeric NOT NULL            -- rise in error when the feature is shuffled; <= 0 = no help
);

CREATE TABLE IF NOT EXISTS ml.projection (
  run_id      int  NOT NULL REFERENCES ml.run,
  railroad    text NOT NULL,
  quarter     text NOT NULL,
  checkpoint  int  NOT NULL,
  method      text NOT NULL CHECK (method IN ('baseline', 'model')),
  projection  numeric NOT NULL,
  low         numeric,                    -- ± the backtest's mean error at the same checkpoint
  high        numeric,
  last_year   numeric,                    -- the same quarter a year earlier
  PRIMARY KEY (run_id, railroad, method)
);
