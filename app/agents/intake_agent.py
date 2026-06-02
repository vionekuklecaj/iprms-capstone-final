from app.schemas.purchase_requisition import PurchaseRequisition
from app.schemas.context import (
    ContextPacket,
    RequestClassification,
    EvidencePointer,
)
from app.services.data_loader import (
    load_budget_snapshot,
    load_approved_vendors,
    load_catalog_items,
    load_cost_center_authority,
)


class IntakeAgent:
    """
    Agent A - Intake & Context

    """

    def run(self, pr: PurchaseRequisition) -> ContextPacket:
        gl_account = self.infer_gl_account(pr)

        budget = load_budget_snapshot(pr.cost_center, gl_account)
        approved_vendors = load_approved_vendors()
        catalog_items = load_catalog_items()
        cost_center_authority = load_cost_center_authority(pr.cost_center)

        classification = self.classify_request(pr)
        evidence_index = self.build_evidence_index(pr)

        return ContextPacket(
            pr=pr,
            classification=classification,
            budget=budget,
            cost_center_authority=cost_center_authority,
            approved_vendors=approved_vendors,
            catalog_items=catalog_items,
            evidence_index=evidence_index
        )

    def infer_gl_account(self, pr: PurchaseRequisition) -> str:
        if pr.gl_account:
            return pr.gl_account

        item_ids = " ".join(
            item.item_id or ""
            for item in pr.line_items
        ).lower()

        descriptions = " ".join(
            item.description
            for item in pr.line_items
        ).lower()

        if any(prefix in item_ids for prefix in ["lap-", "mon-", "doc-", "head-"]):
            return "6100"

        if any(prefix in item_ids for prefix in ["key-", "mou-"]):
            return "6300"

        if "software" in descriptions or "license" in descriptions:
            return "6200"

        return "6100"

    def classify_request(self, pr: PurchaseRequisition) -> RequestClassification:
        text = (
            pr.business_justification + " " +
            " ".join(item.description for item in pr.line_items) + " " +
            " ".join(item.item_id or "" for item in pr.line_items)
        ).lower()

        if "emergency" in text or "urgent" in text:
            return RequestClassification(
                request_type="EMERGENCY_PURCHASE",
                priority="HIGH",
                confidence=0.90,
                reason="Emergency or urgent language found in requisition"
            )

        if (
            "sole source" in text
            or "single source" in text
            or "only supplier" in text
            or "only vendor" in text
            or "proprietary" in text
        ):
            return RequestClassification(
                request_type="SOLE_SOURCE_PURCHASE",
                priority="HIGH",
                confidence=0.90,
                reason="Sole-source language found in business justification"
            )

        if any(prefix in text for prefix in ["lap-", "mon-", "key-", "mou-", "doc-", "head-"]):
            return RequestClassification(
                request_type="IT_EQUIPMENT",
                priority="STANDARD",
                confidence=0.95,
                reason="Catalogue item ID matches IT equipment category"
            )

        if "software" in text or "license" in text or "subscription" in text:
            return RequestClassification(
                request_type="SOFTWARE_OR_LICENSE",
                priority="STANDARD",
                confidence=0.85,
                reason="Software or licensing terminology found"
            )

        return RequestClassification(
            request_type="GENERAL_PURCHASE",
            priority="STANDARD",
            confidence=0.70,
            reason="No specialized request pattern detected"
        )

    def build_evidence_index(self, pr: PurchaseRequisition) -> list[EvidencePointer]:
        evidence_items = []

        for item in pr.line_items:
            evidence_items.append(
                EvidencePointer(
                    line_item_id=item.item_id or "UNKNOWN",
                    source_document="Input PR JSON/PDF/Web Form",
                    budget_source="data/sample_data/budget_snapshot.csv",
                    vendor_source="data/sample_data/approved_vendors.csv",
                    catalogue_source="data/sample_data/catalogue_pricing.csv",
                    policy_source="policies/policy.yaml",
                    notes="Line item linked to source PR, budget snapshot, vendor master, catalogue pricing, and policy pack"
                )
            )

        return evidence_items