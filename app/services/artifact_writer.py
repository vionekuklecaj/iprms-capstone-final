import json
import csv
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parents[2]


def write_json(file_path: Path, data: dict) -> None:
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def write_markdown(file_path: Path, content: str) -> None:
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)


def create_audit_markdown(final_result: dict) -> str:
    lines = ["# Audit Log", ""]

    for step in final_result["audit_log"]["steps"]:
        lines.append(f"## {step['agent']}")
        lines.append(f"- Status: {step['status']}")
        lines.append(f"- Output: {step['output']}")
        lines.append("")

    lines.append("## Final Decision")
    lines.append(f"- Decision: {final_result['final_decision']}")
    lines.append(f"- Reason: {final_result['approval_packet']['reason']}")

    return "\n".join(lines)


def create_exceptions_markdown(compliance_result: dict) -> str:
    lines = ["# Exceptions Report", ""]

    exceptions = compliance_result["exceptions"]

    if not exceptions:
        lines.append("No exceptions found.")
        return "\n".join(lines)

    for index, exception in enumerate(exceptions, start=1):
        lines.append(f"## Exception {index}: {exception['type']}")
        lines.append(f"- Severity: {exception['severity']}")
        lines.append(f"- Message: {exception['message']}")
        lines.append(f"- Next Action: {exception['next_action']}")

        if "related_prs" in exception:
            lines.append(f"- Related PRs: {', '.join(exception['related_prs'])}")

        if "combined_spend" in exception:
            lines.append(f"- Combined Spend: {exception['combined_spend']}")

        if "threshold" in exception:
            lines.append(f"- Threshold: {exception['threshold']}")

        lines.append("")

    return "\n".join(lines)


def create_procurement_summary_markdown(
    pr_id: str,
    budget_result: dict,
    vendor_result: dict,
    compliance_result: dict,
    final_result: dict,
    anomaly_result: dict | None = None
) -> str:
    lines = ["# Procurement Decision Summary", ""]

    lines.append("## PR ID")
    lines.append(pr_id)
    lines.append("")

    lines.append("## Final Decision")
    lines.append(final_result["final_decision"])
    lines.append("")

    lines.append("## Required Approver")
    lines.append(final_result["approval_packet"]["required_approver"])
    lines.append("")

    lines.append("## Reason")
    lines.append(final_result["approval_packet"]["reason"])
    lines.append("")

    lines.append("## Budget Check")
    lines.append(f"- Status: {budget_result['status']}")
    lines.append(f"- Requested Amount: {budget_result['requested_amount']}")
    lines.append(f"- Available Budget: {budget_result['available_budget']}")
    lines.append("")

    lines.append("## Vendor Check")
    lines.append(f"- Vendor: {vendor_result['requested_vendor']}")
    lines.append(f"- Status: {vendor_result['vendor_status']}")
    lines.append(f"- Risk: {vendor_result['vendor_risk']}")
    lines.append("")

    lines.append("## Exceptions")
    if compliance_result["exceptions"]:
        for exception in compliance_result["exceptions"]:
            lines.append(f"- {exception['type']}: {exception['message']}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Anomaly Check")
    if anomaly_result:
        lines.append(f"- Detected: {anomaly_result['anomaly_detected']}")
        lines.append(f"- Type: {anomaly_result['anomaly_type']}")
        lines.append(f"- Combined Spend: {anomaly_result['combined_spend']}")
        lines.append(f"- Threshold: {anomaly_result['threshold']}")
        lines.append(f"- Related PRs: {', '.join(anomaly_result['related_prs'])}")
    else:
        lines.append("- Not performed")

    return "\n".join(lines)


def write_decision_summary_csv(
    file_path: Path,
    pr_id: str,
    budget_result: dict,
    vendor_result: dict,
    compliance_result: dict,
    final_result: dict,
    anomaly_result: dict | None = None
) -> None:
    with open(file_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "pr_id",
                "decision",
                "required_approver",
                "budget_status",
                "vendor_status",
                "exception_count",
                "anomaly_detected"
            ]
        )

        writer.writeheader()
        writer.writerow({
            "pr_id": pr_id,
            "decision": final_result["final_decision"],
            "required_approver": final_result["approval_packet"]["required_approver"],
            "budget_status": budget_result["status"],
            "vendor_status": vendor_result["vendor_status"],
            "exception_count": len(compliance_result["exceptions"]),
            "anomaly_detected": (
                anomaly_result["anomaly_detected"]
                if anomaly_result is not None
                else False
            )
        })


def save_run_artifacts(
    pr_id: str,
    context_packet: dict,
    budget_result: dict,
    vendor_result: dict,
    compliance_result: dict,
    final_result: dict,
    anomaly_result: dict | None = None,
    extraction_result: dict | None = None,
    input_source: str = "JSON",
) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{pr_id}_{timestamp}"
    run_dir = BASE_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if extraction_result is not None:
        extraction_metadata = {
            **extraction_result,
            "classification": context_packet.get("classification")
        }
    else:
        extraction_metadata = {
            "status": "COMPLETED",
            "source_file": context_packet["pr"].get(
                "source_file",
                "JSON input or parsed PR object"
            ),
            "extraction_confidence": context_packet["pr"].get(
                "extraction_confidence",
                1.0
            ),
            "extraction_method": context_packet["pr"].get(
                "extraction_method",
                "Structured JSON input"
            ),
            "evidence": {
                "source_type": "JSON_OR_PARSED_PDF",
                "note": "Structured PR saved after intake and extraction"
            },
            "classification": context_packet.get("classification"),
            "extracted_pr": context_packet["pr"]
        }

    write_json(run_dir / "extracted_pr.json", extraction_metadata)
    write_json(run_dir / "context_packet.json", context_packet)
    write_json(run_dir / "budget_check.json", budget_result)
    write_json(run_dir / "vendor_match.json", vendor_result)

    if anomaly_result is not None:
        write_json(run_dir / "anomaly_check.json", anomaly_result)

    write_json(run_dir / "exceptions.json", {
        "exceptions": compliance_result["exceptions"]
    })

    exceptions_markdown = create_exceptions_markdown(compliance_result)
    write_markdown(run_dir / "exceptions.md", exceptions_markdown)

    write_json(run_dir / "approval_packet.json", final_result["approval_packet"])

    write_json(run_dir / "po_draft.json", {
        "po_draft": final_result["po_draft"]
    })

    

    write_json(run_dir / "metrics.json", {
        "pr_id": pr_id,
        "final_decision": final_result["final_decision"],
        "budget_status": budget_result["status"],
        "vendor_status": vendor_result["vendor_status"],
        "compliance_status": compliance_result["compliance_status"],
        "exception_count": len(compliance_result["exceptions"]),
        "exception_types": [
            exception["type"]
            for exception in compliance_result["exceptions"]
        ],
        "anomaly_detected": (
            anomaly_result["anomaly_detected"]
            if anomaly_result is not None
            else False
        ),
        "anomaly_type": (
            anomaly_result["anomaly_type"]
            if anomaly_result is not None
            else None
        ),
        "po_draft_generated": final_result["po_draft"] is not None,
        "agents_executed": [
            "Agent A - Intake & Context",
            "Agent C - Budget Validation",
            "Agent D - Vendor Matching",
            "Split Order Anomaly Agent",
            "Agent E - Compliance & Policy",
            "Agent H - Orchestrator"
        ],
        "agent_count": 6
    })

    audit_markdown = create_audit_markdown(final_result)
    write_markdown(run_dir / "audit_log.md", audit_markdown)

    procurement_summary = create_procurement_summary_markdown(
        pr_id=pr_id,
        budget_result=budget_result,
        vendor_result=vendor_result,
        compliance_result=compliance_result,
        final_result=final_result,
        anomaly_result=anomaly_result
    )
    write_markdown(run_dir / "procurement_summary.md", procurement_summary)

    write_decision_summary_csv(
        file_path=run_dir / "decision_summary.csv",
        pr_id=pr_id,
        budget_result=budget_result,
        vendor_result=vendor_result,
        compliance_result=compliance_result,
        final_result=final_result,
        anomaly_result=anomaly_result
    )

    
    try:
        from app.services.audit_db import log_pipeline_run
        log_pipeline_run(
            run_id=run_id,
            pr_id=pr_id,
            run_directory=str(run_dir),
            input_source=input_source,
            budget_result=budget_result,
            vendor_result=vendor_result,
            compliance_result=compliance_result,
            final_result=final_result,
            anomaly_result=anomaly_result,
        )
    except Exception:
        pass  

    
    try:
        from app.services.data_loader import append_to_pr_history
        append_to_pr_history(context_packet.get("pr", {}), final_result, vendor_result)
    except Exception:
        pass  

    
    try:
        from app.services.runs_manager import cleanup_old_runs
        cleanup_old_runs()
    except Exception:
        pass  

    return {
        "run_id": run_id,
        "run_directory": str(run_dir)
    }