-- Analysis views: the rules the dashboard (and any analyst in pgAdmin) should build on.
-- Views hold no data, so they are rebuilt from scratch on every start.
DROP SCHEMA IF EXISTS mart CASCADE;
CREATE SCHEMA mart;

-- Originated carloads (network volume; Received double-counts interchange).
-- CP and KCS are rolled into CPKC before the May 2025 merger, so CPKC is one continuous series.
CREATE VIEW mart.originated AS
SELECT c.week_ending,
       c.submission_date,
       coalesce(r.merged_into, c.railroad) AS railroad,
       c.commodity,
       k.segment,
       sum(c.carloads)                     AS carloads,
       bool_or(r.merged_into IS NOT NULL)  AS pro_forma   -- true = predecessors summed
FROM core.carloads c
JOIN core.railroad r USING (railroad)
JOIN core.commodity k USING (commodity)
WHERE c.load_type = 'Originated'
GROUP BY 1, 2, 3, 4, 5;

-- Headline service metrics, one value per railroad and week. Not stitched: CPKC's
-- speed and dwell are a new series from May 2025. Compare each railroad only to itself.
CREATE VIEW mart.service_headline AS
SELECT week_ending, submission_date, railroad, measure, value
FROM core.service_metric
WHERE (measure, variable) IN (('train_speed', 'System'), ('terminal_dwell', 'System Average'), ('cars_online', 'Total'))
  AND subvariable = '';

-- Terminal dwell with map coordinates. A yard is continuous across the CPKC merger
-- (CP's Harvey history continues as CPKC's Harvey); CP and KCS never share a terminal name.
CREATE VIEW mart.terminal_dwell AS
SELECT s.week_ending, coalesce(r.merged_into, s.railroad) AS railroad, s.variable AS terminal,
       s.value AS dwell_hours, t.lat, t.lon
FROM core.service_metric s
JOIN core.railroad r ON r.railroad = s.railroad
JOIN core.terminal t ON t.railroad = coalesce(r.merged_into, s.railroad) AND t.terminal = s.variable
WHERE s.measure = 'terminal_dwell';

-- Grain cars loaded by state and railroad (a weekly count, so it adds up across railroads).
CREATE VIEW mart.grain_by_state AS
SELECT week_ending, railroad, subvariable AS state, value AS cars
FROM core.service_metric
WHERE measure = 'grain_cars_loaded' AND variable = 'All' AND length(subvariable) = 2;  -- 2-letter states only

-- Coal loadings by basin and railroad. Units differ by railroad (CSX reports carloads,
-- others unit trains), so never sum across railroads.
CREATE VIEW mart.coal_by_basin AS
SELECT week_ending, railroad, initcap(variable) AS basin, value AS loadings
FROM core.service_metric
WHERE measure = 'coal_loadings' AND subvariable = 'Loadings Average' AND variable <> 'Other';
