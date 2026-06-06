"""
Agent F — Vendor Risk Analysis

"""

from __future__ import annotations

import json
import os
from typing import Optional

from app.schemas.context import ContextPacket


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a procurement vendor risk analyst. "
    "Your job is to review a vendor selection for a purchase requisition "
    "and produce a short, structured risk assessment. "
    "Be concise and factual. Never invent data not given to you. "
    "Output valid JSON only — no markdown fences, no preamble."
)

_USER_TEMPLATE = """\
Assess the vendor risk for this procurement:

PR ID: {pr_id}
Vendor Name: {vendor_name}
Vendor Status: {vendor_status}
Vendor Risk Level: {vendor_risk}
Total Amount: {total_amount} {currency}
Spend Type: {spend_type}
Items Requested: {items_summary}
Preferred Vendor Match: {preferred_match}
Price Tolerance Issues: {price_issues}

Return a JSON object with exactly these keys:
- risk_score: number 1-10 (10 = highest risk)
- risk_narrative: 2-3 sentence explanation
- due_diligence_required: true or false
- due_diligence_reason: string (why or why not)
- recommended_action: one of [PROCEED, ADDITIONAL_REVIEW, ESCALATE]
"""


def _build_prompt_data(context: ContextPacket, vendor_result: dict) -> dict:
    pr = context.pr
    items_summary = "; ".join(
        f"{item.description} x{item.quantity} @ {item.unit_price}"
        for item in pr.line_items
    )
    currency = pr.line_items[0].currency if pr.line_items else "USD"
    preferred_match = not bool(vendor_result.get("preferred_vendor_issues"))
    price_issues = len(vendor_result.get("price_tolerance_issues", [])) > 0

    return {
        "pr_id": pr.pr_id,
        "vendor_name": vendor_result.get("requested_vendor") or "Unknown",
        "vendor_status": vendor_result.get("vendor_status", "UNKNOWN"),
        "vendor_risk": vendor_result.get("vendor_risk", "UNKNOWN"),
        "total_amount": pr.total_amount,
        "currency": currency,
        "spend_type": pr.spend_type,
        "items_summary": items_summary,
        "preferred_match": preferred_match,
        "price_issues": price_issues,
    }


def _rule_based_risk(vendor_result: dict, total_amount: float) -> dict:
    """Deterministic fallback when no LLM is available."""
    vendor_risk = vendor_result.get("vendor_risk", "LOW")
    vendor_status = vendor_result.get("vendor_status", "UNKNOWN")
    price_issues = vendor_result.get("price_tolerance_issues", [])
    preferred_issues = vendor_result.get("preferred_vendor_issues", [])

    score = 2  # baseline

    if vendor_status not in ("APPROVED",):
        score += 4
    if vendor_risk == "HIGH":
        score += 2
    elif vendor_risk == "MEDIUM":
        score += 1
    if total_amount > 20000:
        score += 1
    if price_issues:
        score += 1
    if preferred_issues:
        score += 1

    score = min(score, 10)

    if score >= 7:
        action = "ESCALATE"
        dd = True
        dd_reason = "High risk score — escalation and due diligence required."
    elif score >= 4:
        action = "ADDITIONAL_REVIEW"
        dd = True
        dd_reason = "Moderate risk — additional review recommended."
    else:
        action = "PROCEED"
        dd = False
        dd_reason = "Low risk — vendor is approved and pricing is within tolerance."

    narrative = (
        f"Vendor risk assessment (rule-based): score {score}/10. "
        f"Vendor status is {vendor_status} with risk level {vendor_risk}. "
        f"Recommended action: {action}."
    )

    return {
        "risk_score": score,
        "risk_narrative": narrative,
        "due_diligence_required": dd,
        "due_diligence_reason": dd_reason,
        "recommended_action": action,
        "assessment_method": "rule_based_fallback",
    }


class VendorRiskAgent:
    """
    Agent F — Vendor Risk Analyst

    LLM-powered vendor risk assessment using LangChain prompt chains.
    CrewAI is used to define the agent's role and backstory, giving it
    a consistent persona and bounded scope.
    """

    def __init__(self):
        self._llm = None
        self._crew_agent = None
        self._setup()

    def _setup(self):
        """Initialize LangChain LLM and CrewAI agent if API key available."""
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

            # Agent role metadata (CrewAI-style, implemented via LangChain system prompt)
            self._agent_role = {
                "role": "Vendor Risk Analyst",
                "goal": (
                    "Assess procurement vendor risk accurately and flag "
                    "situations requiring due diligence or escalation."
                ),
                "backstory": (
                    "You are a senior procurement risk specialist with 15 years "
                    "of experience evaluating vendor risk in enterprise purchasing. "
                    "You apply procurement policy rigorously and flag anything unusual."
                ),
            }

        except Exception:
            self._llm = None
            self._crew_agent = None

    def run(self, context: ContextPacket, vendor_result: dict) -> dict:
        pr = context.pr

        if self._llm is None:
            return {
                **_rule_based_risk(vendor_result, pr.total_amount),
                "agent": "Agent F - Vendor Risk Analyst",
            }

        prompt_data = _build_prompt_data(context, vendor_result)

        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser

            prompt = ChatPromptTemplate.from_messages([
                ("system", _SYSTEM_PROMPT),
                ("human", _USER_TEMPLATE),
            ])

            chain = prompt | self._llm | JsonOutputParser()
            result = chain.invoke(prompt_data)

            return {
                **result,
                "agent": "Agent F - Vendor Risk Analyst",
                "assessment_method": "llm_langchain",
            }

        except Exception as e:
            fallback = _rule_based_risk(vendor_result, pr.total_amount)
            fallback["assessment_method"] = f"rule_based_fallback (llm_error: {type(e).__name__})"
            fallback["agent"] = "Agent F - Vendor Risk Analyst"
            return fallback
