from app.schemas.context import ContextPacket
from app.services.summary_writer import generate_review_summary


class OrchestratorAgent:
    """
    Agent H - Lead Orchestrator

    """

    def run(
        self,
        context: ContextPacket,
        budget_result: dict,
        vendor_result: dict,
        compliance_result: dict
    ) -> dict:
        pr = context.pr

        raw_exceptions = compliance_result.get("exceptions", [])
        deduplicated_exceptions = self._deduplicate_exceptions(raw_exceptions)
        prioritized_exceptions = self._prioritize_exceptions(deduplicated_exceptions)
        standardized_findings = self._standardize_findings(
            context=context,
            prioritized_exceptions=prioritized_exceptions
        )
        exception_categories = self._categorize_exceptions(prioritized_exceptions)
        overall_priority = self._determine_overall_priority(prioritized_exceptions)

        if compliance_result["decision"] == "APPROVE":
            final_decision = "APPROVED"
        else:
            final_decision = "REVIEW_REQUIRED"

        procurement_action = self._determine_procurement_action(
            final_decision=final_decision,
            prioritized_exceptions=prioritized_exceptions
        )

        po_draft = None

        if final_decision == "APPROVED":
            po_draft = {
                "po_status": "DRAFT_READY",
                "source_pr_id": pr.pr_id,
                "vendor_name": pr.vendor_name,
                "cost_center": pr.cost_center,
                "currency": pr.line_items[0].currency if pr.line_items else "USD",
                "line_items": [
                    {
                        "item_id": item.item_id,
                        "description": item.description,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "line_total": item.quantity * item.unit_price
                    }
                    for item in pr.line_items
                ],
                "total_amount": pr.total_amount
            }

        summary_input = {
            "pr_id": pr.pr_id,
            "vendor_name": pr.vendor_name,
            "total_amount": pr.total_amount,
            "currency": pr.line_items[0].currency if pr.line_items else "USD",
            "region": compliance_result.get("regional_context", {}).get("region"),
            "approval_workflow": compliance_result.get("regional_context", {}).get("approval_workflow"),
            "final_decision": final_decision,
            "procurement_action": procurement_action,
            "overall_priority": overall_priority,
            "required_approver": compliance_result["required_approver"],
            "findings": [
                {
                    "type": finding["finding_type"],
                    "severity": finding["severity"],
                    "message": finding["message"],
                    "recommendation": finding["recommendation"],
                }
                for finding in standardized_findings
            ],
        }
        narrative_summary = generate_review_summary(summary_input)

        approval_packet = {
            "pr_id": pr.pr_id,
            "decision": final_decision,
            "procurement_action": procurement_action,
            "overall_priority": overall_priority,
            "required_approver": compliance_result["required_approver"],
            "reason": self._build_reason(prioritized_exceptions),
    
            "narrative_summary": narrative_summary,

            "exception_summary": {
                "raw_exception_count": len(raw_exceptions),
                "deduplicated_exception_count": len(prioritized_exceptions),
                "categories": exception_categories
            },
          
        
            "findings": standardized_findings,
            "routing": {
                "required_approver": compliance_result["required_approver"],
                "approval_escalation_paths": self._extract_escalation_paths(
                    prioritized_exceptions,
                    compliance_result["required_approver"]
                )
            },
            "follow_up_actions": self._extract_follow_up_actions(prioritized_exceptions),
            "evidence": [
                "budget_snapshot.csv",
                "approved_vendors.csv",
                "catalogue_pricing.csv",
                "policy.yaml"
            ]
        }

        audit_log = {
            "steps": [
                {
                    "agent": "Agent A - Intake & Context",
                    "status": "COMPLETED",
                    "output": "Context packet created"
                },
                {
                    "agent": "Agent C - Budget Validation",
                    "status": budget_result["status"],
                    "output": budget_result["reason"]
                },
                {
                    "agent": "Agent D - Vendor Matching",
                    "status": vendor_result["vendor_status"],
                    "output": vendor_result["vendor_reason"]
                },
                {
                    "agent": "Agent E - Compliance & Policy",
                    "status": compliance_result["compliance_status"],
                    "output": compliance_result["decision"]
                },
                {
                    "agent": "Agent H - Orchestration",
                    "status": "COMPLETED",
                    "output": final_decision
                }
            ],
            "orchestration_summary": {
                "procurement_action": procurement_action,
                "overall_priority": overall_priority,
                "deduplicated_exception_count": len(prioritized_exceptions),
                "exception_categories": exception_categories
            }
        }

        return {
            "final_decision": final_decision,
            "procurement_action": procurement_action,
            "overall_priority": overall_priority,
            "approval_packet": approval_packet,
            "po_draft": po_draft,
            "audit_log": audit_log,
            "orchestration_findings": {
                "deduplicated_exceptions": standardized_findings,
                "exception_categories": exception_categories,
                "follow_up_actions": self._extract_follow_up_actions(prioritized_exceptions)
            }
        }

    def _standardize_findings(
        self,
        context: ContextPacket,
        prioritized_exceptions: list[dict]
    ) -> list[dict]:
        """
        Converts policy exceptions into a standardized finding schema.

        Each finding includes:
        - finding identifier
        - category
        - severity
        - confidence
        - rule reference
        - evidence links
        - justification requirement
        - approval escalation path
        """

        standardized_findings = []

        evidence_index = getattr(context, "evidence_index", []) or []

        for index, exception in enumerate(prioritized_exceptions, start=1):
            exception_type = exception.get("type", "UNKNOWN")
            category = self._get_exception_category(exception_type)

            finding_id = f"FINDING-{index:03d}"

            confidence = self._calculate_finding_confidence(exception)

            evidence_links = self._build_evidence_links(
                exception=exception,
                evidence_index=evidence_index
            )

            evidence_status = self._determine_evidence_status(evidence_links)

            recommendation = self._build_recommendation(exception)
            open_questions = self._build_open_questions(exception)

            standardized_finding = {
                "finding_id": finding_id,
                "finding_type": exception_type,
                "finding_category": category,
                "severity": exception.get("severity", "LOW"),
                "confidence": confidence,
                "evidence_required": True,
                "evidence_status": evidence_status,
                "rule_reference": exception.get("rule_reference", "POLICY-GENERAL-001"),
                "message": exception.get("message"),
                "next_action": exception.get("next_action"),
                "recommendation": recommendation,
                "open_questions": open_questions,
                "justification_required": exception.get("justification_required", True),
                "required_justification": exception.get(
                    "required_justification",
                    "Provide supporting justification for this policy exception."
                ),
                "approval_escalation_path": exception.get(
                    "approval_escalation_path",
                    "Manual Review"
                ),
                "evidence_links": evidence_links,
                "source_exception": exception
            }

            standardized_findings.append(standardized_finding)

        return standardized_findings


    def _build_recommendation(self, exception: dict) -> str:
        """
        Builds a human-review recommendation for each finding.
        """

        exception_type = exception.get("type")

        recommendation_by_type = {
            "BUDGET_EXCEEDED": "Request Finance approval for a budget override or reduce the requisition amount.",
            "PERIOD_CAP_EXCEEDED": "Ask Finance to confirm whether the purchase can be moved to a later period or approved as an exception.",
            "BUDGET_DATA_MISSING": "Validate the cost center and GL account mapping before continuing.",
            "CAPEX_THRESHOLD_REVIEW": "Obtain capital expenditure approval before PO generation.",
            "MULTI_CURRENCY_REVIEW": "Ask Finance to review currency handling before approval.",
            "VENDOR_NOT_APPROVED": "Use an approved vendor or submit a vendor exception request.",
            "PREFERRED_VENDOR_MISMATCH": "Confirm why the preferred catalogue supplier was not selected.",
            "INSUFFICIENT_QUOTES": "Attach the required competitive quotes or document a sourcing exception.",
            "BID_THRESHOLD_REVIEW": "Review the attached competitive quotes before approving.",
            "SOLE_SOURCE_REVIEW": "Validate the sole-source rationale before approving.",
            "CATALOGUE_PRICE_TOLERANCE_EXCEEDED": "Review the catalogue price variance and either approve the exception or update the requested price.",
            "SOLE_SOURCE_JUSTIFICATION_MISSING": "Request documented sole-source justification before continuing.",
            "POTENTIAL_SPLIT_ORDER": "Review related requisitions to confirm the purchase was not split to avoid thresholds.",
            "EMERGENCY_PROCUREMENT_REVIEW": "Confirm the emergency reason and expedited approval path.",
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING": "Request the framework agreement or contract reference.",
            "BLANKET_ORDER_REVIEW": "Request blanket order duration, release limit, and usage justification.",
            "LOW_DESCRIPTION_CONFIDENCE": "Request a clearer item description before sourcing or PO generation."
        }

        return recommendation_by_type.get(
            exception_type,
            exception.get("next_action", "Route for manual procurement review.")
        )

    def _build_open_questions(self, exception: dict) -> list[str]:
        """
        Lists open questions that a human reviewer should resolve.
        """

        exception_type = exception.get("type")

        questions_by_type = {
            "BUDGET_EXCEEDED": [
                "Is additional budget available for this cost center and GL account?",
                "Has Finance approved a budget override?"
            ],
            "PERIOD_CAP_EXCEEDED": [
                "Can this purchase be deferred to a later period?",
                "Has Finance approved exceeding the period cap?"
            ],
            "CATALOGUE_PRICE_TOLERANCE_EXCEEDED": [
                "Why does the requested price exceed the approved catalogue tolerance?",
                "Can the vendor match the catalogue price or provide justification for the variance?"
            ],
            "BUDGET_DATA_MISSING": [
                "Is the cost center valid?",
                "Is the GL account mapped to an active budget?"
            ],
            "CAPEX_THRESHOLD_REVIEW": [
                "Does this purchase qualify as CAPEX?",
                "Has the capital approver approved the spend?"
            ],
            "MULTI_CURRENCY_REVIEW": [
                "Which exchange rate should be used?",
                "Has Finance approved the currency handling?"
            ],
            "VENDOR_NOT_APPROVED": [
                "Is there a business reason to use this vendor?",
                "Should the vendor be onboarded or replaced with an approved supplier?"
            ],
            "PREFERRED_VENDOR_MISMATCH": [
                "Why was the preferred catalogue supplier not selected?",
                "Is there a documented price, availability, or service reason?"
            ],
            "INSUFFICIENT_QUOTES": [
                "Have the required competitive quotes been attached?",
                "If not, is there an approved sourcing exception?"
            ],
            "BID_THRESHOLD_REVIEW": [
                "Do the attached quotes satisfy the competitive bidding requirement?",
                "Was the selected vendor justified against the alternatives?"
            ],
            "SOLE_SOURCE_REVIEW": [
                "Is the sole-source rationale valid?",
                "Is competitive sourcing genuinely not possible?"
            ],
            "SOLE_SOURCE_JUSTIFICATION_MISSING": [
                "Why is only one supplier able to fulfill the requirement?",
                "Has the requester provided written sole-source justification?"
            ],
            "POTENTIAL_SPLIT_ORDER": [
                "Are the related requisitions part of the same purchasing need?",
                "Was the purchase split to avoid approval or bid thresholds?"
            ],
            "EMERGENCY_PROCUREMENT_REVIEW": [
                "What is the business impact of the emergency?",
                "Can normal sourcing be bypassed under emergency policy?"
            ],
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING": [
                "Which framework agreement applies?",
                "Is the contract reference valid and active?"
            ],
            "BLANKET_ORDER_REVIEW": [
                "What is the blanket order duration?",
                "What is the maximum release limit?"
            ],
            "LOW_DESCRIPTION_CONFIDENCE": [
                "Is the item description specific enough for sourcing?",
                "Can the requester provide a clearer description or catalogue item?"
            ]
        }

        return questions_by_type.get(
            exception_type,
            ["What additional information is needed before approval?"]
        )


    def _determine_evidence_status(self, evidence_links: list[dict]) -> str:
        """
        Confirms whether a finding has mandatory evidence pointers.
        """

        if not evidence_links:
            return "MISSING"

        if any(link.get("source") == "policy.yaml" for link in evidence_links):
            return "FALLBACK_POLICY_LINKED"

        return "LINKED"       

    def _calculate_finding_confidence(self, exception: dict) -> float:
        """
        Assigns a prototype confidence score to each finding.
        Rule-based findings have high confidence. Data-quality findings are lower.
        """

        exception_type = exception.get("type")

        high_confidence_findings = {
            "BUDGET_EXCEEDED",
            "PERIOD_CAP_EXCEEDED",
            "BUDGET_DATA_MISSING",
            "CAPEX_THRESHOLD_REVIEW",
            "CATALOGUE_PRICE_TOLERANCE_EXCEEDED",
            "VENDOR_NOT_APPROVED",
            "PREFERRED_VENDOR_MISMATCH",
            "INSUFFICIENT_QUOTES",
            "BID_THRESHOLD_REVIEW",
            "SOLE_SOURCE_JUSTIFICATION_MISSING",
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING",
            "BLANKET_ORDER_REVIEW",
            "MULTI_CURRENCY_REVIEW"
        }

        medium_confidence_findings = {
            "SOLE_SOURCE_REVIEW",
            "EMERGENCY_PROCUREMENT_REVIEW",
            "POTENTIAL_SPLIT_ORDER"
        }

        lower_confidence_findings = {
            "LOW_DESCRIPTION_CONFIDENCE"
        }

        if exception_type in high_confidence_findings:
            return 0.95

        if exception_type in medium_confidence_findings:
            return 0.85

        if exception_type in lower_confidence_findings:
            return 0.75

        return 0.80

    def _build_evidence_links(
        self,
        exception: dict,
        evidence_index: list
    ) -> list[dict]:
        """
        Links findings back to available evidence pointers from the context packet.
        """

        exception_type = exception.get("type", "")

        evidence_links = []

        evidence_keywords_by_exception = {
            "BUDGET_EXCEEDED": ["budget", "cost_center"],
            "PERIOD_CAP_EXCEEDED": ["budget", "cost_center"],
            "BUDGET_DATA_MISSING": ["budget", "cost_center"],
            "CAPEX_THRESHOLD_REVIEW": ["budget", "cost_center"],
            "MULTI_CURRENCY_REVIEW": ["budget", "cost_center"],
            "VENDOR_NOT_APPROVED": ["vendor"],
            "PREFERRED_VENDOR_MISMATCH": ["vendor", "catalogue"],
            "INSUFFICIENT_QUOTES": ["policy"],
            "BID_THRESHOLD_REVIEW": ["policy"],
            "SOLE_SOURCE_REVIEW": ["policy"],
            "SOLE_SOURCE_JUSTIFICATION_MISSING": ["policy"],
            "EMERGENCY_PROCUREMENT_REVIEW": ["policy"],
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING": ["policy"],
            "BLANKET_ORDER_REVIEW": ["policy"],
            "POTENTIAL_SPLIT_ORDER": ["policy"],
            "LOW_DESCRIPTION_CONFIDENCE": ["source_pr", "catalogue"]
        }

        keywords = evidence_keywords_by_exception.get(exception_type, ["policy"])

        for evidence in evidence_index:
            evidence_source = getattr(evidence, "source", "")
            evidence_field = getattr(evidence, "field", "")
            evidence_description = getattr(evidence, "description", "")

            combined_text = (
                f"{evidence_source} {evidence_field} {evidence_description}"
            ).lower()

            if any(keyword in combined_text for keyword in keywords):
                evidence_links.append({
                    "source": evidence_source,
                    "field": evidence_field,
                    "description": evidence_description
                })

        if not evidence_links:
            evidence_links.append({
                "source": "policy.yaml",
                "field": exception_type,
                "description": "Policy rule or compliance exception generated by Agent E"
            })

        return evidence_links


    def _deduplicate_exceptions(self, exceptions: list[dict]) -> list[dict]:
        """
        Removes duplicate exception types while preserving the most severe version.
        """

        severity_rank = {
            "HIGH": 3,
            "MEDIUM": 2,
            "LOW": 1
        }

        deduplicated = {}

        for exception in exceptions:
            exception_type = exception.get("type", "UNKNOWN")
            severity = exception.get("severity", "LOW")

            if exception_type not in deduplicated:
                deduplicated[exception_type] = exception
            else:
                existing_severity = deduplicated[exception_type].get("severity", "LOW")

                if severity_rank.get(severity, 0) > severity_rank.get(existing_severity, 0):
                    deduplicated[exception_type] = exception

        return list(deduplicated.values())

    def _prioritize_exceptions(self, exceptions: list[dict]) -> list[dict]:
        """
        Sorts exceptions by severity and then by business-critical category.
        """

        severity_rank = {
            "HIGH": 1,
            "MEDIUM": 2,
            "LOW": 3
        }

        category_rank = {
            "FINANCE": 1,
            "PROCUREMENT_CONTROL": 2,
            "SOURCING": 3,
            "SUPPLIER": 4,
            "DATA_QUALITY": 5,
            "GENERAL": 6
        }

        return sorted(
            exceptions,
            key=lambda exception: (
                severity_rank.get(exception.get("severity", "LOW"), 99),
                category_rank.get(self._get_exception_category(exception.get("type")), 99),
                exception.get("type", "")
            )
        )

    def _categorize_exceptions(self, exceptions: list[dict]) -> dict:
        """
        Groups exceptions into actionable procurement categories.
        """

        categories = {}

        for exception in exceptions:
            exception_type = exception.get("type")
            category = self._get_exception_category(exception_type)

            if category not in categories:
                categories[category] = []

            categories[category].append(exception_type)

        return categories

    def _get_exception_category(self, exception_type: str | None) -> str:
        """
        Maps exception types to actionable processing categories.
        """

        finance_exceptions = {
            "BUDGET_EXCEEDED",
            "PERIOD_CAP_EXCEEDED",
            "BUDGET_DATA_MISSING",
            "CAPEX_THRESHOLD_REVIEW",
            "MULTI_CURRENCY_REVIEW"
        }

        supplier_exceptions = {
            "VENDOR_NOT_APPROVED",
            "PREFERRED_VENDOR_MISMATCH",
            "CATALOGUE_PRICE_TOLERANCE_EXCEEDED"
        }

        sourcing_exceptions = {
            "INSUFFICIENT_QUOTES",
            "BID_THRESHOLD_REVIEW",
            "SOLE_SOURCE_REVIEW",
            "SOLE_SOURCE_JUSTIFICATION_MISSING"
        }

        procurement_control_exceptions = {
            "POTENTIAL_SPLIT_ORDER",
            "EMERGENCY_PROCUREMENT_REVIEW",
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING",
            "BLANKET_ORDER_REVIEW"
        }

        data_quality_exceptions = {
            "LOW_DESCRIPTION_CONFIDENCE"
        }

        if exception_type in finance_exceptions:
            return "FINANCE"
        if exception_type in supplier_exceptions:
            return "SUPPLIER"
        if exception_type in sourcing_exceptions:
            return "SOURCING"
        if exception_type in procurement_control_exceptions:
            return "PROCUREMENT_CONTROL"
        if exception_type in data_quality_exceptions:
            return "DATA_QUALITY"

        return "GENERAL"

    def _determine_overall_priority(self, exceptions: list[dict]) -> str:
        """
        Determines overall case priority from prioritized findings.
        """

        severities = {
            exception.get("severity", "LOW")
            for exception in exceptions
        }

        if "HIGH" in severities:
            return "HIGH"
        if "MEDIUM" in severities:
            return "MEDIUM"
        if "LOW" in severities:
            return "LOW"

        return "NONE"

    def _determine_procurement_action(
        self,
        final_decision: str,
        prioritized_exceptions: list[dict]
    ) -> str:
        """
        Determines the next procurement processing action.
        """

        exception_types = {
            exception.get("type")
            for exception in prioritized_exceptions
        }

        if final_decision == "APPROVED":
            return "GENERATE_PO_DRAFT"

        if "POTENTIAL_SPLIT_ORDER" in exception_types:
            return "ESCALATE_TO_PROCUREMENT_COMPLIANCE"

        if (
            "BUDGET_EXCEEDED" in exception_types
            or "PERIOD_CAP_EXCEEDED" in exception_types
            or "BUDGET_DATA_MISSING" in exception_types
            or "MULTI_CURRENCY_REVIEW" in exception_types
        ):
            return "ROUTE_TO_FINANCE_REVIEW"

        if (
            "INSUFFICIENT_QUOTES" in exception_types
            or "SOLE_SOURCE_JUSTIFICATION_MISSING" in exception_types
            or "SOLE_SOURCE_REVIEW" in exception_types
            or "BID_THRESHOLD_REVIEW" in exception_types
        ):
            return "ROUTE_TO_SOURCING_REVIEW"

        if (
            "VENDOR_NOT_APPROVED" in exception_types
            or "PREFERRED_VENDOR_MISMATCH" in exception_types
        ):
            return "ROUTE_TO_SUPPLIER_REVIEW"

        if "EMERGENCY_PROCUREMENT_REVIEW" in exception_types:
            return "ROUTE_TO_EMERGENCY_APPROVAL"

        if (
            "FRAMEWORK_AGREEMENT_REFERENCE_MISSING" in exception_types
            or "BLANKET_ORDER_REVIEW" in exception_types
        ):
            return "ROUTE_TO_PROCUREMENT_MANAGER"

        if "LOW_DESCRIPTION_CONFIDENCE" in exception_types:
            return "REQUEST_DATA_CLARIFICATION"

        return "ROUTE_FOR_MANUAL_REVIEW"

    def _extract_follow_up_actions(self, exceptions: list[dict]) -> list[str]:
        """
        Extracts actionable follow-up steps from findings.
        """

        follow_up_actions = []

        for exception in exceptions:
            action = exception.get("next_action") or exception.get("required_justification")

            if action and action not in follow_up_actions:
                follow_up_actions.append(action)

        return follow_up_actions

    def _extract_escalation_paths(
        self,
        exceptions: list[dict],
        fallback_approver: str
    ) -> list[str]:
        """
        Extracts approval escalation paths from findings.
        """

        escalation_paths = []

        for exception in exceptions:
            path = exception.get("approval_escalation_path", fallback_approver)

            if path and path not in escalation_paths:
                escalation_paths.append(path)

        if not escalation_paths:
            escalation_paths.append(fallback_approver)

        return escalation_paths

    def _build_reason(self, prioritized_exceptions: list[dict]) -> str:
        if prioritized_exceptions:
            exception_types = [
                exception["type"]
                for exception in prioritized_exceptions
            ]
            return "Review required due to: " + ", ".join(exception_types)

        return (
            "Purchase requisition passed budget, vendor, and compliance checks."
        )