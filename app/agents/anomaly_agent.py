
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.context import ContextPacket
from app.services.data_loader import (
    load_pr_history,
    load_pr_history_from_runs,
    load_policy,
)

LOOKBACK_DAYS = 30
MIN_RELATED_PRS = 1


class AnomalyAgent:
  

    def run(self, context: ContextPacket) -> dict:
        policy = load_policy()

        runs_history = load_pr_history_from_runs() or []
        csv_history_raw = load_pr_history() or []

        
        csv_history = [r for r in csv_history_raw if r.get("created_date")]

        
        history_by_id: dict[str, dict] = {r["pr_id"]: r for r in csv_history}
        for record in runs_history:
            history_by_id[record["pr_id"]] = record
        all_history = list(history_by_id.values())

        
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        windowed: list[dict] = []

        for record in all_history:
            created = record.get("created_date") or record.get("completed_at")
            if not created:
                continue
            try:
                if isinstance(created, str):
                    created_dt = datetime.fromisoformat(
                        created.replace("Z", "+00:00")
                    )
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                else:
                    created_dt = created
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)

                if created_dt >= cutoff:
                    windowed.append(record)
            except (ValueError, TypeError):
                pass

        current_pr = context.pr
        threshold = policy["bid_threshold"]["amount"]

        current_item = current_pr.line_items[0].item_id if current_pr.line_items else None
        current_vendor = current_pr.vendor_name
        current_cost_center = current_pr.cost_center  
        current_amount = current_pr.total_amount

        matching_records: list[dict] = []

        for record in windowed:
            
            if record["pr_id"] == current_pr.pr_id:
                continue

            
            record_cc = record.get("cost_center") or record.get("department")
            current_match_key = record.get("cost_center") or current_cost_center

            
            if record.get("cost_center"):
                cc_match = record["cost_center"] == current_cost_center
            else:
                cc_match = record.get("department") == current_pr.department

            if (
                cc_match
                and record.get("vendor_name") == current_vendor
                and record.get("item_id") == current_item
            ):
                matching_records.append(record)

        related_spend = current_amount + sum(
            float(r.get("total_amount", 0)) for r in matching_records
        )
        related_prs = [r["pr_id"] for r in matching_records]

        anomaly_detected = (
            related_spend > threshold
            and len(related_prs) >= MIN_RELATED_PRS
        )

        return {
            "current_pr_id": current_pr.pr_id,
            "current_amount": current_amount,
            "anomaly_detected": anomaly_detected,
            "anomaly_type": "POTENTIAL_SPLIT_ORDER" if anomaly_detected else None,
            "combined_spend": related_spend,
            "threshold": threshold,
            "related_pr_count": len(related_prs),
            "related_prs": related_prs[:5],
            "lookback_days": LOOKBACK_DAYS,
            "history_window_size": len(windowed),
            "match_criteria": {
                "cost_center": current_cost_center,
                "vendor_name": current_vendor,
                "item_id": current_item,
            },
        }
