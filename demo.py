
import json
import sys
from pathlib import Path

from app.schemas.purchase_requisition import PurchaseRequisition
from app.pipeline import run_pipeline


def run_demo(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        pr_data = json.load(f)

    pr = PurchaseRequisition(**pr_data)
    result = run_pipeline(pr, input_source="CLI")

    final = result["final_result"]
    packet = final["approval_packet"]
    vr = result.get("vendor_risk", {})

    print("\n" + "=" * 65)
    print("IPRMS v2.0 — PROCUREMENT PIPELINE RESULT")
    print("=" * 65)
    print(f"\nPR ID:          {pr.pr_id}")
    print(f"Requestor:      {pr.requestor_name}")
    print(f"Department:     {pr.department} / {pr.cost_center}")
    print(f"Total Amount:   {pr.total_amount:.2f} {pr.line_items[0].currency}")
    print(f"\nFinal Decision: {final['final_decision']}")
    print(f"Approver:       {packet['required_approver']}")
    print(f"Reason:         {packet['reason']}")
    print(f"\nVendor Risk:    {vr.get('risk_score', 'N/A')}/10  ({vr.get('recommended_action', 'N/A')})")

    exceptions = result["compliance"]["exceptions"]
    if exceptions:
        print(f"\nExceptions ({len(exceptions)}):")
        for exc in exceptions:
            print(f"  [{exc['severity']}] {exc['type']} — {exc['message']}")
    else:
        print("\nExceptions: None")

    anomaly = result["anomaly_check"]
    if anomaly["anomaly_detected"]:
        print(f"\n⚠  Split-order detected. Related PRs: {anomaly['related_prs']}")

    if final.get("approval_packet", {}).get("narrative_summary"):
        print(f"\nAI Summary:\n  {packet['narrative_summary']}")

    run_dir = result["run_artifacts"].get("run_directory", "—")
    print(f"\nArtifacts: {run_dir}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python demo.py data/pr_bundles/pr_auto_approve.json")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    run_demo(str(path))
