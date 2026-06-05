from app.schemas.context import ContextPacket
from app.services.data_loader import load_policy


class ComplianceAgent:
    """
    Agent E - Compliance & Policy Engine

    """

    def enrich_exception_findings(self, exceptions: list[dict], required_approver: str) -> list[dict]:
        """
        Adds detailed policy finding metadata to every compliance exception:
        - rule reference
        - justification requirement
        - required evidence / justification
        - approval escalation path
        """

        rule_catalog = {
            "BUDGET_EXCEEDED": {
                "rule_reference": "FIN-BUDGET-001",
                "justification_required": True,
                "required_justification": "Provide Finance-approved budget override or revise the requisition amount.",
                "approval_escalation_path": "Finance / FP&A"
            },
            "PERIOD_CAP_EXCEEDED": {
                "rule_reference": "FIN-PERIOD-001",
                "justification_required": True,
                "required_justification": "Provide Finance approval for exceeding the current period spending cap.",
                "approval_escalation_path": "Finance / FP&A"
            },
            "BUDGET_DATA_MISSING": {
                "rule_reference": "FIN-BUDGET-002",
                "justification_required": True,
                "required_justification": "Provide valid cost center and GL account budget mapping.",
                "approval_escalation_path": "Finance / FP&A"
            },
            "CAPEX_THRESHOLD_REVIEW": {
                "rule_reference": "FIN-CAPEX-001",
                "justification_required": True,
                "required_justification": "Provide capital expenditure justification and capital approver sign-off.",
                "approval_escalation_path": "Capital Approver"
            },
            "VENDOR_NOT_APPROVED": {
                "rule_reference": "VENDOR-APPROVAL-001",
                "justification_required": True,
                "required_justification": "Provide approved vendor exception justification or select an approved supplier.",
                "approval_escalation_path": "Procurement Manager"
            },
            "CATALOGUE_PRICE_TOLERANCE_EXCEEDED": {
                "rule_reference": "VENDOR-PRICE-001",
                "justification_required": True,
                "required_justification": "Explain why requested pricing exceeds approved catalogue tolerance or update the PR price.",
                "approval_escalation_path": "Procurement Manager"
            },
            "PREFERRED_VENDOR_MISMATCH": {
                "rule_reference": "VENDOR-PREFERRED-001",
                "justification_required": True,
                "required_justification": "Explain why the preferred catalogue supplier was not selected.",
                "approval_escalation_path": "Procurement Manager"
            },
            "POTENTIAL_SPLIT_ORDER": {
                "rule_reference": "PROC-SPLIT-001",
                "justification_required": True,
                "required_justification": "Explain related requisitions and confirm the purchase was not split to avoid approval thresholds.",
                "approval_escalation_path": "Procurement Compliance"
            },
            "LOW_DESCRIPTION_CONFIDENCE": {
                "rule_reference": "DATA-QUALITY-001",
                "justification_required": True,
                "required_justification": "Provide a specific item description sufficient for pricing, sourcing, and PO generation.",
                "approval_escalation_path": "Procurement Analyst"
            },
            "SOLE_SOURCE_REVIEW": {
                "rule_reference": "SOURCING-SOLE-001",
                "justification_required": True,
                "required_justification": "Provide documented sole-source rationale and confirm why competitive sourcing is not possible.",
                "approval_escalation_path": "Sourcing Manager"
            },
            "SOLE_SOURCE_JUSTIFICATION_MISSING": {
                "rule_reference": "SOURCING-SOLE-002",
                "justification_required": True,
                "required_justification": "Document why only one supplier can fulfill the requirement.",
                "approval_escalation_path": "Procurement Manager"
            },
            "BID_THRESHOLD_REVIEW": {
                "rule_reference": "SOURCING-BID-001",
                "justification_required": True,
                "required_justification": "Attach and review the required competitive vendor quotes.",
                "approval_escalation_path": "Manager"
            },
            "INSUFFICIENT_QUOTES": {
                "rule_reference": "SOURCING-BID-002",
                "justification_required": True,
                "required_justification": "Attach the minimum number of required competitive quotes or provide a sourcing exception.",
                "approval_escalation_path": "Procurement Manager"
            },
            "EMERGENCY_PROCUREMENT_REVIEW": {
                "rule_reference": "PROC-EMERGENCY-001",
                "justification_required": True,
                "required_justification": "Provide emergency reason, business impact, and confirmation of expedited approval need.",
                "approval_escalation_path": "Emergency Approver"
            },
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING": {
                "rule_reference": "PROC-FRAMEWORK-001",
                "justification_required": True,
                "required_justification": "Provide valid framework agreement or contract reference.",
                "approval_escalation_path": "Procurement Manager"
            },
            "BLANKET_ORDER_REVIEW": {
                "rule_reference": "PROC-BLANKET-001",
                "justification_required": True,
                "required_justification": "Provide blanket order duration, release limit, and usage justification.",
                "approval_escalation_path": "Procurement Manager"
            },
            "MULTI_CURRENCY_REVIEW": {
                "rule_reference": "FIN-CURRENCY-001",
                "justification_required": True,
                "required_justification": "Provide Finance review for currency handling and exchange-rate impact.",
                "approval_escalation_path": "Finance / FP&A"
            }
        }

        enriched_exceptions = []

        for exception in exceptions:
            exception_type = exception.get("type")
            rule_details = rule_catalog.get(exception_type, {
                "rule_reference": "POLICY-GENERAL-001",
                "justification_required": True,
                "required_justification": "Provide supporting justification for this policy exception.",
                "approval_escalation_path": required_approver
            })

            enriched_exception = {
                **exception,
                "rule_reference": rule_details["rule_reference"],
                "justification_required": rule_details["justification_required"],
                "required_justification": rule_details["required_justification"],
                "approval_escalation_path": rule_details["approval_escalation_path"]
            }

            enriched_exceptions.append(enriched_exception)

        return enriched_exceptions

    def _resolve_regional_policy(self, policy: dict, context) -> tuple:
        """
        Resolves region (from the cost-center authority) to its regional policy
        block in policy.yaml. Returns (region_name, regional_policy_dict_or_None).
        Matching is case-insensitive; unknown/missing regions fall back to global.
        """
        regional_policies = policy.get("regional_policies", {})

        region = None
        authority = getattr(context, "cost_center_authority", None)
        if authority is not None:
            region = getattr(authority, "region", None)

        if not region:
            return None, None

        for name, config in regional_policies.items():
            if name.lower() == region.lower():
                return name, config

        return region, None

    def run(
        self,
        context: ContextPacket,
        budget_result: dict,
        vendor_result: dict,
        anomaly_result: dict | None = None
    ) -> dict:
        policy = load_policy()

        region, regional_policy = self._resolve_regional_policy(policy, context)

        if regional_policy:
            bid_threshold_amount = regional_policy.get("bid_threshold_amount", policy["bid_threshold"]["amount"])
            required_quotes = regional_policy.get("required_quotes", policy["bid_threshold"]["required_quotes"])
            regional_currency = regional_policy.get("currency", "USD")
            approval_workflow = regional_policy.get("approval_workflow", "DEFAULT")
        else:
            bid_threshold_amount = policy["bid_threshold"]["amount"]
            required_quotes = policy["bid_threshold"]["required_quotes"]
            regional_currency = "USD"
            approval_workflow = "DEFAULT"

        pr = context.pr
        total_amount = pr.total_amount
        exceptions = []

        approval_thresholds = policy["approval_thresholds"]
        auto_limit = approval_thresholds["auto_approval_limit"]
        manager_limit = approval_thresholds["manager_limit"]
        director_limit = approval_thresholds["director_limit"]

        if total_amount <= auto_limit:
            required_approver = "Auto Approval"
        elif total_amount <= manager_limit:
            required_approver = "Manager"
        elif total_amount <= director_limit:
            required_approver = "Director"
        else:
            required_approver = "VP"

        
        # Budget / finance policy exceptions
        
        if (
            policy["budget_policy"]["block_if_budget_exceeded"]
            and budget_result["status"] == "FAIL"
        ):
            budget_reason = budget_result["reason"]

            if "period" in budget_reason.lower():
                exception_type = "PERIOD_CAP_EXCEEDED"
                message = "Requested amount exceeds period spending cap"
                next_action = "Route to Finance / FP&A for period cap review"
            elif "no budget" in budget_reason.lower():
                exception_type = "BUDGET_DATA_MISSING"
                message = "No budget snapshot found for this cost center and GL account"
                next_action = "Route to Finance / FP&A to validate budget setup"
            else:
                exception_type = "BUDGET_EXCEEDED"
                message = "Requested amount exceeds available budget"
                next_action = "Route to Finance / FP&A"

            exceptions.append({
                "type": exception_type,
                "severity": "HIGH",
                "message": message,
                "next_action": next_action
            })

        if budget_result.get("capex_threshold_status") == "REVIEW_REQUIRED":
            exceptions.append({
                "type": "CAPEX_THRESHOLD_REVIEW",
                "severity": "MEDIUM",
                "message": "CAPEX purchase exceeds capital approval threshold",
                "next_action": "Route for capital expenditure approval",
                "requested_amount": budget_result["requested_amount"],
                "capex_threshold": budget_result["capex_threshold"]
            })

        
        # Vendor and sourcing policy
        
        if (
            policy["vendor_policy"]["approved_vendor_required"]
            and vendor_result["vendor_status"] != "APPROVED"
        ):
            exceptions.append({
                "type": "VENDOR_NOT_APPROVED",
                "severity": "HIGH",
                "message": "Requested vendor is not approved",
                "next_action": "Request justification or select approved vendor"
            })

        if (
            vendor_result.get("vendor_status") == "APPROVED"
            and vendor_result.get("preferred_vendor_issues")
        ):
            exceptions.append({
                "type": "PREFERRED_VENDOR_MISMATCH",
                "severity": "MEDIUM",
                "message": "Requested supplier is approved but is not the preferred catalogue supplier for one or more line items",
                "next_action": "Review supplier selection or switch to preferred catalogue vendor",
                "issues": vendor_result["preferred_vendor_issues"]
            })
        if vendor_result.get("price_tolerance_issues"):
            exceptions.append({
                "type": "CATALOGUE_PRICE_TOLERANCE_EXCEEDED",
                "severity": "MEDIUM",
                "message": "One or more requested prices exceed the allowed catalogue price tolerance",
                "next_action": "Review pricing variance or update the requisition to match approved catalogue pricing",
                "issues": vendor_result["price_tolerance_issues"]
            })

        
        # Split-order / anomaly policy
        
        if anomaly_result and anomaly_result["anomaly_detected"]:
            exceptions.append({
                "type": anomaly_result["anomaly_type"],
                "severity": "HIGH",
                "message": "Potential split-order pattern detected across related purchase requisitions",
                "next_action": "Route to procurement compliance for manual review",
                "related_prs": anomaly_result["related_prs"],
                "combined_spend": anomaly_result["combined_spend"],
                "threshold": anomaly_result["threshold"]
            })

        
        # Vague item description / extraction confidence style review
        
        vague_description_terms = [
            "it equipment",
            "equipment",
            "hardware",
            "services",
            "misc",
            "miscellaneous",
            "general equipment",
            "unknown",
            "unknown item"
        ]

        catalog_match_by_item_id = {
            matched_item["item_id"]: matched_item.get("catalog_match", False)
            for matched_item in vendor_result.get("matched_items", [])
        }

        for item in pr.line_items:
            description = item.description.lower().strip()
            item_id = item.item_id or "UNKNOWN"

            catalog_match = catalog_match_by_item_id.get(item_id, False)

            is_generic_description = (
                description in vague_description_terms
                or item_id.upper().startswith("UNK")
            )

            if not catalog_match or is_generic_description:
                exceptions.append({
                    "type": "LOW_DESCRIPTION_CONFIDENCE",
                    "severity": "MEDIUM",
                    "message": f"Item description may be too vague for reliable pricing: {item.description}",
                    "next_action": "Route to buyer/procurement analyst for clarification"
                })
                break

        
        # Sole-source review
        
        justification = pr.business_justification.lower()
        sole_source_justification = (
            pr.sole_source_justification.strip()
            if pr.sole_source_justification
            else ""
        )

        sole_source_keywords = [
            "sole source",
            "single source",
            "only supplier",
            "only vendor",
            "exclusive vendor",
            "proprietary",
            "no alternative"
        ]

        sole_source_detected = (
            pr.sole_source_requested
            or any(keyword in justification for keyword in sole_source_keywords)
        )

        if sole_source_detected:
            if not sole_source_justification:
                exceptions.append({
                    "type": "SOLE_SOURCE_JUSTIFICATION_MISSING",
                    "severity": "HIGH",
                    "message": "Sole-source procurement was detected but no justification was provided",
                    "next_action": "Provide documented sole-source justification before approval"
                })
            else:
                exceptions.append({
                    "type": "SOLE_SOURCE_REVIEW",
                    "severity": "MEDIUM",
                    "message": "Potential sole-source procurement detected",
                    "next_action": "Review justification and verify sole-source approval",
                    "sole_source_justification": sole_source_justification
                })

        
        # Emergency procurement review
        
        procurement_type = pr.procurement_type.upper()
        emergency_text = " ".join([
            pr.business_justification or "",
            pr.emergency_reason or "",
            procurement_type
        ]).lower()

        emergency_keywords = [
            "emergency",
            "urgent",
            "critical",
            "downtime",
            "service outage",
            "business continuity"
        ]

        if (
            procurement_type == "EMERGENCY"
            or any(keyword in emergency_text for keyword in emergency_keywords)
        ):
            exceptions.append({
                "type": "EMERGENCY_PROCUREMENT_REVIEW",
                "severity": "MEDIUM",
                "message": "Emergency procurement path triggered",
                "next_action": "Route for expedited emergency approval",
                "emergency_reason": pr.emergency_reason
            })

        
        # Framework agreement validation
        
        if procurement_type == "FRAMEWORK_AGREEMENT":
            if not pr.contract_reference:
                exceptions.append({
                    "type": "FRAMEWORK_AGREEMENT_REFERENCE_MISSING",
                    "severity": "MEDIUM",
                    "message": "Framework agreement purchase is missing a contract reference",
                    "next_action": "Provide framework agreement or contract reference"
                })

        
        # Blanket order validation
        
        if procurement_type == "BLANKET_ORDER":
            if (
                pr.blanket_order_duration_months is None
                or pr.blanket_order_release_limit is None
            ):
                exceptions.append({
                    "type": "BLANKET_ORDER_REVIEW",
                    "severity": "MEDIUM",
                    "message": "Blanket order is missing duration or release limit",
                    "next_action": "Provide blanket order duration and release limit"
                })

        
        # Multi-currency review
        
        currencies = {
            item.currency.upper()
            for item in pr.line_items
        }

        if len(currencies) > 1 or any(currency != "USD" for currency in currencies):
            exceptions.append({
                "type": "MULTI_CURRENCY_REVIEW",
                "severity": "MEDIUM",
                "message": "Purchase requisition contains non-USD or multiple currencies",
                "next_action": "Route to Finance / FP&A for currency review",
                "currencies": sorted(currencies)
            })

        
        # Competitive bid threshold (region-aware)
        
        if total_amount > bid_threshold_amount:
            if pr.quotes_received < required_quotes:
                exceptions.append({
                    "type": "INSUFFICIENT_QUOTES",
                    "severity": "HIGH",
                    "message": f"Purchase exceeds bid threshold but only {pr.quotes_received} quote(s) were provided",
                    "next_action": f"Attach at least {required_quotes} competitive vendor quotes",
                    "quotes_received": pr.quotes_received,
                    "required_quotes": required_quotes
                })
            else:
                exceptions.append({
                    "type": "BID_THRESHOLD_REVIEW",
                    "severity": "MEDIUM",
                    "message": "Purchase exceeds bid threshold and has required competitive quotes attached",
                    "next_action": "Review attached competitive quotes before approval",
                    "quotes_received": pr.quotes_received,
                    "required_quotes": required_quotes
                })

        
        # Final compliance decision and routing
        
        if len(exceptions) == 0:
            compliance_status = "PASS"
            decision = "APPROVE"
        else:
            compliance_status = "REVIEW_REQUIRED"
            decision = "ROUTE_FOR_REVIEW"

            high_risk_types = [
                exception["type"]
                for exception in exceptions
                if exception["severity"] == "HIGH"
            ]

            medium_risk_types = [
                exception["type"]
                for exception in exceptions
                if exception["severity"] == "MEDIUM"
            ]

            if "POTENTIAL_SPLIT_ORDER" in high_risk_types:
                required_approver = "Procurement Compliance"
            elif (
                "BUDGET_EXCEEDED" in high_risk_types
                or "PERIOD_CAP_EXCEEDED" in high_risk_types
                or "BUDGET_DATA_MISSING" in high_risk_types
            ):
                required_approver = "Finance / FP&A"
            elif (
                "VENDOR_NOT_APPROVED" in high_risk_types
                or "INSUFFICIENT_QUOTES" in high_risk_types
                or "SOLE_SOURCE_JUSTIFICATION_MISSING" in high_risk_types
            ):
                required_approver = "Procurement Manager"
            elif "EMERGENCY_PROCUREMENT_REVIEW" in medium_risk_types:
                required_approver = "Emergency Approver"
            elif "CAPEX_THRESHOLD_REVIEW" in medium_risk_types:
                required_approver = "Capital Approver"
            elif "MULTI_CURRENCY_REVIEW" in medium_risk_types:
                required_approver = "Finance / FP&A"
            elif "FRAMEWORK_AGREEMENT_REFERENCE_MISSING" in medium_risk_types:
                required_approver = "Procurement Manager"
            elif "BLANKET_ORDER_REVIEW" in medium_risk_types:
                required_approver = "Procurement Manager"
            elif (
                "PREFERRED_VENDOR_MISMATCH" in medium_risk_types
                or "CATALOGUE_PRICE_TOLERANCE_EXCEEDED" in medium_risk_types
            ):
                required_approver = "Procurement Manager"
            elif "SOLE_SOURCE_REVIEW" in medium_risk_types:
                required_approver = "Sourcing Manager"
            elif "LOW_DESCRIPTION_CONFIDENCE" in medium_risk_types:
                required_approver = "Procurement Analyst"

        exceptions = self.enrich_exception_findings(
            exceptions=exceptions,
            required_approver=required_approver
        )

        return {
            "compliance_status": compliance_status,
            "decision": decision,
            "required_approver": required_approver,
            "exceptions": exceptions,
            "policy_checks": {
                "approval_threshold_checked": True,
                "budget_policy_checked": True,
                "vendor_policy_checked": True,
                "preferred_vendor_checked": True,
                "split_order_checked": True,
                "bid_threshold_checked": True,
                "sole_source_checked": True,
                "description_confidence_checked": True,
                "capex_threshold_checked": True,
                "emergency_procurement_checked": True,
                "framework_agreement_checked": True,
                "blanket_order_checked": True,
                "multi_currency_checked": True
            },
            "regional_context": {
                "region": region,
                "regional_policy_applied": regional_policy is not None,
                "bid_threshold_amount": bid_threshold_amount,
                "required_quotes": required_quotes,
                "currency": regional_currency,
                "approval_workflow": approval_workflow,
            },
        }