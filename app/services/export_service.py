
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone


def runs_to_csv(runs: list[dict]) -> bytes:
    
    if not runs:
        return b"No data\n"

    fieldnames = [
        "run_id", "pr_id", "input_source", "final_decision",
        "required_approver", "exception_count", "anomaly_detected",
        "total_amount", "available_budget", "budget_status",
        "vendor_name", "vendor_status", "compliance_status",
        "completed_at",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for run in runs:
        writer.writerow(run)

    return buf.getvalue().encode("utf-8")


def exceptions_to_csv(exceptions: list[dict]) -> bytes:
    
    if not exceptions:
        return b"No exceptions\n"

    fieldnames = [
        "exception_type", "severity", "category",
        "message", "next_action", "rule_reference", "raised_at",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for exc in exceptions:
        writer.writerow(exc)

    return buf.getvalue().encode("utf-8")


def audit_stats_to_csv(stats: dict, exception_summary: list[dict]) -> bytes:
    
    buf = io.StringIO()

    buf.write("IPRMS Audit Statistics Export\n")
    buf.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")

    buf.write("Summary\n")
    for k, v in stats.items():
        buf.write(f"{k},{v}\n")

    buf.write("\nException Frequency\n")
    buf.write("exception_type,severity,count\n")
    for row in exception_summary:
        buf.write(f"{row['exception_type']},{row['severity']},{row['count']}\n")

    return buf.getvalue().encode("utf-8")
