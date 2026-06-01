from pydantic import BaseModel
from typing import List, Optional
from app.schemas.purchase_requisition import PurchaseRequisition


class BudgetSnapshot(BaseModel):
    cost_center: str
    gl_account: str
    gl_account_name: str
    available_budget: float
    period: str
    period_cap: float
    period_spend_to_date: float
    capex_threshold: float
    currency: str = "USD"


class ApprovedVendor(BaseModel):
    vendor_id: str
    vendor_name: str
    status: str
    risk_level: str = "LOW"


class CatalogItem(BaseModel):
    item_id: str
    description: str
    approved_vendor: str
    unit_price: float
    currency: str = "USD"

class RequestClassification(BaseModel):
    request_type: str
    priority: str
    confidence: float
    reason: str

class CostCenterAuthority(BaseModel):
    cost_center: str
    department: str
    approver_role: str
    finance_owner: str
    region: str

class EvidencePointer(BaseModel):
    line_item_id: str
    source_document: str
    budget_source: str
    vendor_source: str
    catalogue_source: str
    policy_source: str
    notes: str

class ContextPacket(BaseModel):
    pr: PurchaseRequisition
    classification: Optional[RequestClassification] = None
    budget: Optional[BudgetSnapshot] = None
    cost_center_authority: Optional[CostCenterAuthority] = None
    approved_vendors: List[ApprovedVendor] = []
    catalog_items: List[CatalogItem] = []
    evidence_index: List[EvidencePointer] = []