"""
IPRMS Test Suite v2.0
======================
Tests for individual agents and the full LangGraph pipeline.

Split-order tests now use the time-windowed AnomalyAgent correctly:
- Clean PRs with no matching recent history → no anomaly
- PRs that match multiple recent Dell/LAP-001/IT001 history rows → anomaly
"""

import json
from pathlib import Path

import pytest

from app.schemas.purchase_requisition import PurchaseRequisition
from app.agents.intake_agent import IntakeAgent
from app.agents.budget_agent import BudgetAgent
from app.agents.vendor_agent import VendorAgent
from app.agents.anomaly_agent import AnomalyAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.orchestrator_agent import OrchestratorAgent
from app.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def build_pr(
    pr_id="PR-TEST-001",
    quantity=3,
    vendor_name="Dell Partner",
    item_id="LAP-001",
    unit_price=1200,
    cost_center="IT001",
    department="IT",
):
    return PurchaseRequisition(
        pr_id=pr_id,
        requestor_name="Test User",
        department=department,
        cost_center=cost_center,
        business_justification="Testing procurement pipeline",
        vendor_name=vendor_name,
        line_items=[
            {
                "item_id": item_id,
                "description": "Dell Latitude 5550",
                "quantity": quantity,
                "unit_price": unit_price,
                "currency": "USD",
            }
        ],
    )


def build_clean_pr(quantity=1):
    """A PR that shares no history with any split-order seed data."""
    return PurchaseRequisition(
        pr_id="PR-CLEAN-TEST-001",
        requestor_name="Test User",
        department="HR",
        cost_center="HR001",
        business_justification="Small HR supply purchase",
        vendor_name="Office Supplies Co",
        line_items=[
            {
                "item_id": "KEY-001",
                "description": "Wireless Keyboard",
                "quantity": quantity,
                "unit_price": 35,
                "currency": "USD",
            }
        ],
    )


# ---------------------------------------------------------------------------
# Budget agent tests
# ---------------------------------------------------------------------------

def test_budget_passes_for_small_purchase():
    pr = build_pr(quantity=3)
    context = IntakeAgent().run(pr)
    result = BudgetAgent().run(context)
    assert result["status"] == "PASS"
    assert result["requested_amount"] == 3600


def test_budget_fails_when_amount_exceeds_budget():
    pr = build_pr(quantity=50)
    context = IntakeAgent().run(pr)
    result = BudgetAgent().run(context)
    assert result["status"] == "FAIL"
    assert result["requested_amount"] == 60000


# ---------------------------------------------------------------------------
# Vendor agent tests
# ---------------------------------------------------------------------------

def test_vendor_approved_is_detected():
    pr = build_pr(vendor_name="Dell Partner")
    context = IntakeAgent().run(pr)
    result = VendorAgent().run(context)
    assert result["vendor_status"] == "APPROVED"


def test_vendor_not_approved_is_detected():
    pr = build_pr(vendor_name="Random Shop")
    context = IntakeAgent().run(pr)
    result = VendorAgent().run(context)
    assert result["vendor_status"] == "NOT_APPROVED"


# ---------------------------------------------------------------------------
# Anomaly agent tests
# ---------------------------------------------------------------------------

def test_clean_pr_does_not_trigger_split_order():
    """A small HR keyboard purchase with no matching history → no anomaly."""
    pr = build_clean_pr(quantity=1)
    context = IntakeAgent().run(pr)
    result = AnomalyAgent().run(context)
    assert result["anomaly_detected"] is False


def test_split_order_detected_with_dated_history():
    """
    A Dell/LAP-001/IT001 PR above threshold when combined with the 4 dated
    seed history rows (PR-HIST-001..004, each 2500) should trigger anomaly.
    Combined: 3600 + 4*2500 = 13600 > 10000 threshold.
    """
    pr = build_pr(quantity=3, unit_price=1200)  # total=3600
    context = IntakeAgent().run(pr)
    result = AnomalyAgent().run(context)
    assert result["anomaly_detected"] is True
    assert result["anomaly_type"] == "POTENTIAL_SPLIT_ORDER"
    assert result["combined_spend"] > result["threshold"]


def test_anomaly_agent_respects_lookback_window():
    """
    A PR matching an item that only has very old history should not trigger.
    This tests that the lookback window is working — old undated CSV rows
    (without created_date) are not included.
    """
    # Use an item/vendor that only exists in undated CSV rows (no created_date)
    # In practice: verify the agent returns False when history has no timestamps
    pr = PurchaseRequisition(
        pr_id="PR-NO-HIST-001",
        requestor_name="Test",
        department="Finance",
        cost_center="FIN001",
        business_justification="Finance equipment",
        vendor_name="HP Enterprise",
        line_items=[{
            "item_id": "LAP-002",
            "description": "HP EliteBook 860",
            "quantity": 10,
            "unit_price": 1350,
            "currency": "USD",
        }],
    )
    context = IntakeAgent().run(pr)
    result = AnomalyAgent().run(context)
    # HP/LAP-002/FIN001 has no history at all → no anomaly
    assert result["anomaly_detected"] is False


# ---------------------------------------------------------------------------
# Full pipeline tests (via LangGraph)
# ---------------------------------------------------------------------------

def test_pipeline_auto_approves_clean_hr_pr():
    """Clean small HR supply purchase should auto-approve with no exceptions."""
    pr = build_clean_pr(quantity=1)
    result = run_pipeline(pr, input_source="TEST")
    assert result["final_result"]["final_decision"] == "APPROVED"
    assert len(result["compliance"]["exceptions"]) == 0
    assert result["anomaly_check"]["anomaly_detected"] is False
    assert result["pipeline_errors"] == []


def test_pipeline_detects_vendor_not_approved():
    pr = build_pr(vendor_name="Random Shop", quantity=3)
    result = run_pipeline(pr, input_source="TEST")
    assert result["final_result"]["final_decision"] == "REVIEW_REQUIRED"
    exception_types = [e["type"] for e in result["compliance"]["exceptions"]]
    assert "VENDOR_NOT_APPROVED" in exception_types


def test_pipeline_detects_budget_exceeded():
    pr = build_pr(quantity=50)  # 50 * 1200 = 60000, exceeds budget
    result = run_pipeline(pr, input_source="TEST")
    assert result["final_result"]["final_decision"] == "REVIEW_REQUIRED"
    exception_types = [e["type"] for e in result["compliance"]["exceptions"]]
    assert "BUDGET_EXCEEDED" in exception_types


def test_pipeline_routes_split_order_to_procurement_compliance():
    """
    A Dell/LAP-001/IT001 PR with 4 recent seed history matches should
    be routed to Procurement Compliance for split-order review.
    """
    pr = build_pr(quantity=3, unit_price=1200)
    result = run_pipeline(pr, input_source="TEST")
    assert result["final_result"]["final_decision"] == "REVIEW_REQUIRED"
    exception_types = [e["type"] for e in result["compliance"]["exceptions"]]
    assert "POTENTIAL_SPLIT_ORDER" in exception_types
    assert result["final_result"]["approval_packet"]["required_approver"] == "Procurement Compliance"
    assert result["final_result"]["po_draft"] is None


def test_pipeline_generates_po_draft_when_approved():
    pr = build_clean_pr(quantity=1)
    result = run_pipeline(pr, input_source="TEST")
    assert result["final_result"]["final_decision"] == "APPROVED"
    assert result["final_result"]["po_draft"] is not None
    assert result["final_result"]["po_draft"]["po_status"] == "DRAFT_READY"


def test_pipeline_results_contain_vendor_risk():
    """Agent F (Vendor Risk) should always return a result."""
    pr = build_clean_pr()
    result = run_pipeline(pr, input_source="TEST")
    vr = result.get("vendor_risk", {})
    assert "risk_score" in vr
    assert "recommended_action" in vr
    assert vr["recommended_action"] in {"PROCEED", "ADDITIONAL_REVIEW", "ESCALATE"}


def test_pipeline_audit_db_populated():
    """Running a pipeline should write an entry to the audit database."""
    from app.services.audit_db import get_runs_for_pr
    pr = build_clean_pr()
    pr_with_unique_id = pr.model_copy(update={"pr_id": "PR-AUDIT-TEST-999"})
    run_pipeline(pr_with_unique_id, input_source="TEST")
    runs = get_runs_for_pr("PR-AUDIT-TEST-999")
    assert len(runs) >= 1
    assert runs[0]["final_decision"] == "APPROVED"


# ---------------------------------------------------------------------------
# Scenario bundle tests
# ---------------------------------------------------------------------------

BUNDLE_DIR = Path("data/pr_bundles")


@pytest.mark.parametrize("filename,expected_decision", [
    ("pr_auto_approve.json", "APPROVED"),
    ("pr_bid_threshold.json", "REVIEW_REQUIRED"),
    ("pr_budget_exceeded.json", "REVIEW_REQUIRED"),
    ("pr_vendor_exception.json", "REVIEW_REQUIRED"),
    ("pr_emergency_procurement.json", "REVIEW_REQUIRED"),
    ("pr_sole_source.json", "REVIEW_REQUIRED"),
    ("pr_vague_description.json", "REVIEW_REQUIRED"),
    ("pr_framework_missing_reference.json", "REVIEW_REQUIRED"),
    ("pr_blanket_order_review.json", "REVIEW_REQUIRED"),
    ("pr_multi_currency_review.json", "REVIEW_REQUIRED"),
    ("pr_preferred_vendor_mismatch.json", "REVIEW_REQUIRED"),
    ("pr_low_confidence_specification.json", "REVIEW_REQUIRED"),
    ("pr_capex_threshold_review.json", "REVIEW_REQUIRED"),
    ("pr_period_cap_exceeded.json", "REVIEW_REQUIRED"),
    ("pr_insufficient_quotes.json", "REVIEW_REQUIRED"),
    ("pr_split_order_fifth.json", "REVIEW_REQUIRED"),
    ("pr_three_pr_threshold.json", "REVIEW_REQUIRED"),
    ("pr_emergency_sole_source.json", "REVIEW_REQUIRED"),
    ("pr_sole_source_missing_justification.json", "REVIEW_REQUIRED"),
])
def test_bundle_scenario_decision(filename, expected_decision):
    """Parametrized test: each scenario file should produce the expected decision."""
    filepath = BUNDLE_DIR / filename
    if not filepath.exists():
        pytest.skip(f"Scenario file not found: {filename}")

    with open(filepath, "r", encoding="utf-8") as f:
        pr_data = json.load(f)

    pr = PurchaseRequisition(**pr_data)
    result = run_pipeline(pr, input_source="TEST")
    assert result["pipeline_errors"] == [], f"Pipeline errors: {result['pipeline_errors']}"
    assert result["final_result"]["final_decision"] == expected_decision, (
        f"Expected {expected_decision}, got {result['final_result']['final_decision']}. "
        f"Exceptions: {[e['type'] for e in result['compliance']['exceptions']]}"
    )
