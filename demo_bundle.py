
import json
import sys
from pathlib import Path

import yaml

from app.schemas.purchase_requisition import PurchaseRequisition
from app.pipeline import run_pipeline


def run_bundle(bundle_path: str):
    bundle_dir = Path(bundle_path)
    manifest_path = bundle_dir / "manifest.yaml"

    if not manifest_path.exists():
        print(f"manifest.yaml not found in {bundle_dir}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    req_path = (bundle_dir / manifest["input"]["requisition_file"]).resolve()
    if not req_path.exists():
        print(f"Requisition file not found: {req_path}")
        sys.exit(1)

    with open(req_path, "r", encoding="utf-8") as f:
        pr_data = json.load(f)

    pr = PurchaseRequisition(**pr_data)
    result = run_pipeline(pr, input_source="BUNDLE")

    final = result["final_result"]
    packet = final["approval_packet"]
    expected = manifest.get("expected_result", {})

    print("\n" + "=" * 65)
    print("IPRMS v2.0 — PR BUNDLE PIPELINE RESULT")
    print("=" * 65)
    print(f"\nBundle ID:  {manifest['bundle_id']}")
    print(f"Scenario:   {manifest['scenario_name']}")
    print(f"PR ID:      {pr.pr_id}")

    print("\nDecision")
    print("-" * 65)
    print(f"  Actual:   {final['final_decision']}")
    print(f"  Approver: {packet['required_approver']}")

    if expected:
        match = (
            final["final_decision"] == expected.get("final_decision")
            and packet["required_approver"] == expected.get("required_approver")
        )
        print(f"\nExpected")
        print("-" * 65)
        print(f"  Decision: {expected.get('final_decision', '—')}")
        print(f"  Approver: {expected.get('required_approver', '—')}")
        print(f"\n  Match: {'✓ PASS' if match else '✗ FAIL'}")

    print(f"\nArtifacts: {result['run_artifacts'].get('run_directory', '—')}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python demo_bundle.py data/pr_bundles/bundle_auto_approve")
        sys.exit(1)
    run_bundle(sys.argv[1])
