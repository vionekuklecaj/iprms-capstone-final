
from __future__ import annotations

import json
import os
from typing import Optional

from app.schemas.purchase_requisition import PurchaseRequisition
from app.schemas.context import RequestClassification




_SYSTEM_PROMPT = (
    "You are a procurement intake specialist. "
    "Your job is to classify a purchase requisition and assess its risk signals. "
    "Be concise, objective, and grounded only in the data provided. "
    "Output valid JSON only — no markdown fences, no preamble."
)

_USER_TEMPLATE = """\
Classify this purchase requisition:

PR ID: {pr_id}
Department: {department}
Cost Center: {cost_center}
Business Justification: {business_justification}
Vendor: {vendor_name}
Spend Type: {spend_type}
Procurement Type: {procurement_type}
Total Amount: {total_amount}
Items: {items_summary}
Sole Source Requested: {sole_source_requested}
Emergency Reason: {emergency_reason}
Quotes Received: {quotes_received}

Return a JSON object with exactly these keys:
- request_type: one of [IT_EQUIPMENT, SOFTWARE_OR_LICENSE, OFFICE_SUPPLIES, PROFESSIONAL_SERVICES, EMERGENCY_PURCHASE, SOLE_SOURCE_PURCHASE, FRAMEWORK_ORDER, BLANKET_ORDER, GENERAL_PURCHASE]
- priority: one of [HIGH, STANDARD, LOW]
- confidence: float 0.0-1.0
- reason: 1-2 sentence explanation of your classification
- risk_signals: list of strings describing any procurement risk signals detected (empty list if none)
- suggested_gl_account: string like "6100" or null
"""



def _rule_based_classify(pr: PurchaseRequisition) -> dict:
    text = (
        pr.business_justification + " " +
        " ".join(item.description for item in pr.line_items) + " " +
        " ".join(item.item_id or "" for item in pr.line_items)
    ).lower()

    if "emergency" in text or "urgent" in text:
        return {
            "request_type": "EMERGENCY_PURCHASE",
            "priority": "HIGH",
            "confidence": 0.90,
            "reason": "Emergency or urgent language found in requisition.",
            "risk_signals": ["Emergency procurement path"],
            "suggested_gl_account": None,
            "assessment_method": "rule_based_fallback",
        }

    if any(kw in text for kw in ["sole source", "single source", "only supplier", "only vendor", "proprietary"]):
        return {
            "request_type": "SOLE_SOURCE_PURCHASE",
            "priority": "HIGH",
            "confidence": 0.90,
            "reason": "Sole-source language found in business justification.",
            "risk_signals": ["Sole source procurement"],
            "suggested_gl_account": None,
            "assessment_method": "rule_based_fallback",
        }

    if any(prefix in text for prefix in ["lap-", "mon-", "key-", "mou-", "doc-", "head-"]):
        return {
            "request_type": "IT_EQUIPMENT",
            "priority": "STANDARD",
            "confidence": 0.95,
            "reason": "Catalogue item ID matches IT equipment category.",
            "risk_signals": [],
            "suggested_gl_account": "6100",
            "assessment_method": "rule_based_fallback",
        }

    if "software" in text or "license" in text or "subscription" in text:
        return {
            "request_type": "SOFTWARE_OR_LICENSE",
            "priority": "STANDARD",
            "confidence": 0.85,
            "reason": "Software or licensing terminology found.",
            "risk_signals": [],
            "suggested_gl_account": "6200",
            "assessment_method": "rule_based_fallback",
        }

    return {
        "request_type": "GENERAL_PURCHASE",
        "priority": "STANDARD",
        "confidence": 0.70,
        "reason": "No specialized request pattern detected.",
        "risk_signals": [],
        "suggested_gl_account": None,
        "assessment_method": "rule_based_fallback",
    }


class PRClassificationAgent:
    

    def __init__(self):
        self._llm = None
        self._crew_agent = None
        self._setup()

    def _setup(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return

        try:
            from langchain_anthropic import ChatAnthropic

            self._llm = ChatAnthropic(
                model="claude-haiku-4-5-20251001",
                api_key=api_key,
                max_tokens=512,
                temperature=0,
            )

            
            self._agent_role = {
                "role": "Procurement Intake Specialist",
                "goal": (
                    "Accurately classify purchase requisitions, detect risk signals, "
                    "and ensure downstream agents receive a well-structured context packet."
                ),
                "backstory": (
                    "You are an experienced procurement intake analyst who has processed "
                    "thousands of purchase requisitions across IT, finance, operations, and "
                    "emergency procurement. You spot unusual patterns immediately."
                ),
            }

        except Exception:
            self._llm = None
            self._crew_agent = None

    def classify(self, pr: PurchaseRequisition) -> dict:
        
        if self._llm is None:
            return _rule_based_classify(pr)

        items_summary = "; ".join(
            f"{item.description} ({item.item_id}) x{item.quantity} @ {item.unit_price} {item.currency}"
            for item in pr.line_items
        )

        prompt_data = {
            "pr_id": pr.pr_id,
            "department": pr.department,
            "cost_center": pr.cost_center,
            "business_justification": pr.business_justification,
            "vendor_name": pr.vendor_name or "Not specified",
            "spend_type": pr.spend_type,
            "procurement_type": pr.procurement_type,
            "total_amount": pr.total_amount,
            "items_summary": items_summary,
            "sole_source_requested": pr.sole_source_requested,
            "emergency_reason": pr.emergency_reason or "None",
            "quotes_received": pr.quotes_received,
        }

        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser

            prompt = ChatPromptTemplate.from_messages([
                ("system", _SYSTEM_PROMPT),
                ("human", _USER_TEMPLATE),
            ])

            chain = prompt | self._llm | JsonOutputParser()
            result = chain.invoke(prompt_data)
            result["assessment_method"] = "llm_langchain"
            return result

        except Exception as e:
            fallback = _rule_based_classify(pr)
            fallback["assessment_method"] = f"rule_based_fallback (llm_error: {type(e).__name__})"
            return fallback

    def to_request_classification(self, pr: PurchaseRequisition) -> RequestClassification:
        
        result = self.classify(pr)
        return RequestClassification(
            request_type=result.get("request_type", "GENERAL_PURCHASE"),
            priority=result.get("priority", "STANDARD"),
            confidence=float(result.get("confidence", 0.70)),
            reason=result.get("reason", "Classification completed."),
        )
