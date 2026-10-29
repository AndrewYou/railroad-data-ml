"""Email alerts. Locally they land in Mailpit (http://localhost:8025). Without SMTP_HOST they only go to the log
(and, in GitHub Actions, the run summary)."""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

MAX_LINES = 20


def send(subject: str, body: str) -> None:
    log.info("%s\n%s", subject, body)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):  # in GitHub Actions: show on the run's page too
        with open(summary, "a") as f:
            f.write(f"### {subject}\n```\n{body}\n```\n")
    host = os.environ.get("SMTP_HOST")
    if not host:
        return
    message = EmailMessage()
    message["Subject"] = f"[rail-data] {subject}"
    message["From"] = os.environ.get("ALERT_FROM", "rail-pipeline@localhost")
    message["To"] = os.environ.get("ALERT_TO", "data-team@localhost")
    message.set_content(body)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "25"))) as smtp:
        smtp.send_message(message)


def run_summary(conn, run_ids: list[int]) -> tuple[str, str]:
    """Subject and body for one load: what ran, what needs an engineer, and what history changed."""
    runs = conn.execute("""
        SELECT run_id, dataset, status, rows_fetched, rows_changed, rows_held, revisions, error
        FROM ops.job_run WHERE run_id = ANY(%s) ORDER BY run_id""", (run_ids,)).fetchall()
    issues = conn.execute("""
        SELECT check_name, action, coalesce(railroad, '-'), detail, count(*)
        FROM ops.issue WHERE run_id = ANY(%s)
        GROUP BY 1, 2, 3, 4 ORDER BY count(*) DESC, 1, 3""", (run_ids,)).fetchall()
    revisions = conn.execute("""
        SELECT dataset, railroad, count(*), min(week_ending), max(week_ending),
               sum(new_value - old_value) FILTER (WHERE dataset = 'carloads')
        FROM ops.revision WHERE run_id = ANY(%s)
        GROUP BY 1, 2 ORDER BY 1, 2""", (run_ids,)).fetchall()
    latest_week = conn.execute("SELECT max(week_ending) FROM core.carloads").fetchone()[0]

    failed = [dataset for _, dataset, status, *_ in runs if status != "succeeded"]
    if failed:
        subject = f"FAILED: {', '.join(failed)} load. Published data unchanged"
    elif issues:
        subject = f"Loaded through week ending {latest_week}: {len(issues)} issue(s) to review"
    else:
        subject = f"Loaded through week ending {latest_week}"

    lines = ["Runs:"]
    for run_id, dataset, status, fetched, changed, held, revised, error in runs:
        lines.append(f"  {dataset} (run {run_id}): {status}" + (f": {error}" if error else
                     f". {fetched:,} rows fetched, {changed:,} new or changed, {held:,} held back, {revised:,} revised"))

    lines += ["", "Issues for engineering:"]
    lines += [f"  [{check}] {railroad}: {detail}" + (f" ({n:,} rows {action})" if n > 1 or action == "held" else "")
              for check, action, railroad, detail, n in issues[:MAX_LINES]] or ["  none"]
    if len(issues) > MAX_LINES:
        lines.append(f"  ...and {len(issues) - MAX_LINES} more")

    lines += ["", "Revisions to history:"]
    lines += [f"  {dataset} / {railroad}: {n:,} values revised, weeks {first} to {last}"
              + (f", net {net:+,} carloads" if net is not None else "")
              for dataset, railroad, n, first, last, net in revisions] or ["  none"]

    ids = ", ".join(map(str, run_ids))
    lines += ["", f"Details: SELECT * FROM ops.issue WHERE run_id IN ({ids});",
              f"         SELECT * FROM ops.revision WHERE run_id IN ({ids});"]
    return subject, "\n".join(lines)
