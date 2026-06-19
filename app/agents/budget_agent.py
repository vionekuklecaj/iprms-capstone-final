from app.schemas.context import ContextPacket


class BudgetAgent:
    

    def run(self, context: ContextPacket) -> dict:
        requested_amount = context.pr.total_amount
        spend_type = context.pr.spend_type.upper()

        if context.budget is None:
            return {
                "status": "FAIL",
                "reason": "No budget snapshot found for cost center and GL account",
                "requested_amount": requested_amount,
                "available_budget": 0,
                "cost_center": context.pr.cost_center,
                "gl_account": context.pr.gl_account,
                "spend_type": spend_type,
                "checks": {
                    "available_budget_checked": False,
                    "gl_account_checked": False,
                    "period_cap_checked": False,
                    "capex_threshold_checked": False
                }
            }

        budget = context.budget

        remaining_budget = budget.available_budget - requested_amount
        projected_period_spend = (
            budget.period_spend_to_date + requested_amount
        )

        available_budget_pass = requested_amount <= budget.available_budget
        period_cap_pass = projected_period_spend <= budget.period_cap

        capex_threshold_status = "NOT_APPLICABLE"
        capex_threshold_exceeded = False

        if spend_type == "CAPEX":
            capex_threshold_exceeded = (
                requested_amount > budget.capex_threshold
            )
            capex_threshold_status = (
                "REVIEW_REQUIRED"
                if capex_threshold_exceeded
                else "PASS"
            )

        if not available_budget_pass:
            status = "FAIL"
            reason = "Requested amount exceeds available budget"
        elif not period_cap_pass:
            status = "FAIL"
            reason = "Requested amount exceeds period spending cap"
        elif capex_threshold_exceeded:
            status = "REVIEW_REQUIRED"
            reason = "CAPEX purchase exceeds approval threshold"
        else:
            status = "PASS"
            reason = "Requested amount is within budget, GL account, and period controls"

        return {
            "status": status,
            "reason": reason,
            "cost_center": budget.cost_center,
            "gl_account": budget.gl_account,
            "gl_account_name": budget.gl_account_name,
            "spend_type": spend_type,
            "requested_amount": requested_amount,
            "available_budget": budget.available_budget,
            "remaining_budget_after_purchase": remaining_budget,
            "period": budget.period,
            "period_cap": budget.period_cap,
            "period_spend_to_date": budget.period_spend_to_date,
            "projected_period_spend": projected_period_spend,
            "period_cap_status": (
                "PASS"
                if period_cap_pass
                else "FAIL"
            ),
            "capex_threshold": budget.capex_threshold,
            "capex_threshold_status": capex_threshold_status,
            "checks": {
                "available_budget_checked": True,
                "gl_account_checked": True,
                "period_cap_checked": True,
                "capex_threshold_checked": spend_type == "CAPEX"
            }
        }