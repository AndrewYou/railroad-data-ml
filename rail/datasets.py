"""The two source datasets: where they come from and how a source row becomes a published row."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    name: str
    socrata_id: str
    source_fields: tuple[str, ...]  # API fields we stage (as text)
    table: str                      # published table
    keys: tuple[str, ...]           # its primary key
    value: str                      # its value column
    clean_sql: str                  # stage -> typed table columns, plus `problem` (NULL = row is fine)

    def key_match(self, a: str, b: str) -> str:
        """SQL condition: rows aliased `a` and `b` have the same key."""
        return " AND ".join(f"{a}.{k} = {b}.{k}" for k in self.keys)

    def series_label(self, alias: str) -> str:
        """SQL for a readable series name, e.g. 'Grain / Originated' or 'train_speed / System'."""
        parts = [f"nullif({alias}.{k}, '')" for k in self.keys if k not in ("week_ending", "railroad")]
        return f"concat_ws(' / ', {', '.join(parts)})"


CARLOADS = Dataset(
    name="carloads",
    socrata_id="tb7q-kn5i",
    source_fields=("date", "submission_date", "railroad", "commodity", "type", "carloads"),
    table="core.carloads",
    keys=("week_ending", "railroad", "commodity", "load_type"),
    value="carloads",
    clean_sql="""
        SELECT s.date::timestamp::date            AS week_ending,
               s.submission_date::timestamp::date AS submission_date,
               s.railroad, s.commodity,
               s.type                              AS load_type,
               s.carloads::numeric                 AS carloads,  -- missing stays NULL; 0 is a real zero
               CASE WHEN r.railroad IS NULL  THEN format('unknown railroad: %s', s.railroad)
                    WHEN c.commodity IS NULL THEN format('unknown commodity: %s', s.commodity)
                    WHEN coalesce(s.type, '') NOT IN ('Originated', 'Received')
                                             THEN format('unknown load type: %s', s.type)
               END AS problem,
               to_jsonb(s) AS source_row
        FROM stage s
        LEFT JOIN core.railroad  r ON r.railroad = s.railroad
        LEFT JOIN core.commodity c ON c.commodity = s.commodity""",
)

# Duplicates the carloads dataset; used only to reconcile the two sources, never published.
SERVICE_CARLOADS_COPY = "Weekly Carloads By 23 Commodity Categories"

SERVICE = Dataset(
    name="service",
    socrata_id="axkm-yjzy",
    source_fields=("measure", "date", "submission_date", "railroad", "variable", "subvariable", "value"),
    table="core.service_metric",
    keys=("week_ending", "railroad", "measure", "variable", "subvariable"),
    value="value",
    clean_sql=f"""
        SELECT s.date::timestamp::date            AS week_ending,
               s.submission_date::timestamp::date AS submission_date,
               s.railroad, m.measure, s.variable,
               coalesce(s.subvariable, '')         AS subvariable,  -- '' so it can be part of the key
               s.value::numeric                    AS value,        -- blank stays NULL, never 0
               CASE WHEN r.railroad IS NULL THEN format('unknown railroad: %s', s.railroad)
                    WHEN m.measure IS NULL  THEN format('unknown measure: %s', s.measure)
                    WHEN s.variable IS NULL THEN 'missing variable'
               END AS problem,
               to_jsonb(s) AS source_row
        FROM stage s
        LEFT JOIN core.railroad r ON r.railroad = s.railroad
        LEFT JOIN core.measure  m ON m.source_name = s.measure
        WHERE s.measure IS DISTINCT FROM '{SERVICE_CARLOADS_COPY}'""",
)

ALL = (CARLOADS, SERVICE)  # load order matters: the service load reconciles against published carloads
