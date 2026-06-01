from pydantic import BaseModel, Field
from typing import List, Optional


class PRLineItem(BaseModel):
    item_id: Optional[str] = None
    description: str
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    currency: str = "USD"


class PurchaseRequisition(BaseModel):
    pr_id: str
    requestor_name: str
    department: str
    cost_center: str
    business_justification: str
    vendor_name: Optional[str] = None

    # Finance / budget metadata
    gl_account: Optional[str] = None
    spend_type: str = "OPEX"

    # Advanced procurement scenario metadata
    procurement_type: str = "STANDARD"
    contract_reference: Optional[str] = None
    emergency_reason: Optional[str] = None
    blanket_order_duration_months: Optional[int] = None
    blanket_order_release_limit: Optional[float] = None

    # Sourcing / bidding metadata
    quotes_received: int = 0
    sole_source_requested: bool = False
    sole_source_justification: Optional[str] = None

    line_items: List[PRLineItem]

    @property
    def total_amount(self) -> float:
        return sum(item.quantity * item.unit_price for item in self.line_items)