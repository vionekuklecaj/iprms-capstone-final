import csv
import json
import yaml
from pathlib import Path

from app.schemas.context import (
    BudgetSnapshot,
    ApprovedVendor,
    CatalogItem,
    CostCenterAuthority,
)


BASE_DIR = Path(__file__).resolve().parents[2]


def load_budget_snapshot(
    cost_center: str,
    gl_account: str | None = None
) -> BudgetSnapshot | None:
    file_path = BASE_DIR / "data" / "sample_data" / "budget_snapshot.csv"

    matching_cost_center_row = None

    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            if row["cost_center"] != cost_center:
                continue

            if matching_cost_center_row is None:
                matching_cost_center_row = row

            if gl_account is None or row["gl_account"] == gl_account:
                return BudgetSnapshot(
                    cost_center=row["cost_center"],
                    gl_account=row["gl_account"],
                    gl_account_name=row["gl_account_name"],
                    available_budget=float(row["available_budget"]),
                    period=row["period"],
                    period_cap=float(row["period_cap"]),
                    period_spend_to_date=float(row["period_spend_to_date"]),
                    capex_threshold=float(row["capex_threshold"]),
                    currency=row["currency"]
                )

    if matching_cost_center_row is not None and gl_account is None:
        row = matching_cost_center_row
        return BudgetSnapshot(
            cost_center=row["cost_center"],
            gl_account=row["gl_account"],
            gl_account_name=row["gl_account_name"],
            available_budget=float(row["available_budget"]),
            period=row["period"],
            period_cap=float(row["period_cap"]),
            period_spend_to_date=float(row["period_spend_to_date"]),
            capex_threshold=float(row["capex_threshold"]),
            currency=row["currency"]
        )

    return None


def load_approved_vendors() -> list[ApprovedVendor]:
    file_path = BASE_DIR / "data" / "sample_data" / "approved_vendors.csv"
    vendors = []

    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            vendors.append(
                ApprovedVendor(
                    vendor_id=row["vendor_id"],
                    vendor_name=row["vendor_name"],
                    status=row["status"],
                    risk_level=row["risk_level"]
                )
            )

    return vendors


def load_catalog_items() -> list[CatalogItem]:
    file_path = BASE_DIR / "data" / "sample_data" / "catalogue_pricing.csv"
    items = []

    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            items.append(
                CatalogItem(
                    item_id=row["item_id"],
                    description=row["description"],
                    approved_vendor=row["approved_vendor"],
                    unit_price=float(row["unit_price"]),
                    currency=row["currency"]
                )
            )

    return items


def load_policy() -> dict:
    file_path = BASE_DIR / "policies" / "policy.yaml"

    with open(file_path, mode="r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_pr_history() -> list[dict]:
    """
    Load PR history from the CSV file.
    Passes through the 'created_date' column when present so the
    AnomalyAgent can apply its time-window filter correctly.
    """
    file_path = BASE_DIR / "data" / "sample_data" / "pr_history.csv"
    history = []

    if not file_path.exists():
        return history

    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            record = {
                "pr_id": row["pr_id"],
                "department": row["department"],
                "vendor_name": row["vendor_name"],
                "item_id": row["item_id"],
                "total_amount": float(row["total_amount"]),
            }
            # Pass through optional timestamp column
            if "created_date" in row and row["created_date"].strip():
                record["created_date"] = row["created_date"].strip()

            history.append(record)

    return history


def load_pr_history_from_runs() -> list[dict]:
    """
    Load PR history from past pipeline run folders.
    Derives a timestamp from the run folder name (format: PR-ID_YYYYMMDD_HHMMSS)
    so the AnomalyAgent can include these records in its time-window filter.
    """
    from datetime import timezone
    import re as _re

    runs_dir = BASE_DIR / "runs"
    history = []

    if not runs_dir.exists():
        return history

    _ts_pattern = _re.compile(r"_(\d{8})_(\d{6})$")

    for run_folder in sorted(runs_dir.iterdir()):
        if not run_folder.is_dir():
            continue

        extracted_pr_path = run_folder / "extracted_pr.json"

        if not extracted_pr_path.exists():
            continue

        with open(extracted_pr_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if "extracted_pr" in data:
            pr_data = data["extracted_pr"]
        else:
            pr_data = data

        if not pr_data.get("line_items"):
            continue

        first_item = pr_data["line_items"][0]
        total_amount = sum(
            item["quantity"] * item["unit_price"]
            for item in pr_data["line_items"]
        )

        # Derive timestamp from folder name (e.g. PR-001_20260617_210000)
        created_date = None
        ts_match = _ts_pattern.search(run_folder.name)
        if ts_match:
            date_str, time_str = ts_match.groups()
            try:
                from datetime import datetime
                dt = datetime.strptime(
                    f"{date_str}_{time_str}", "%Y%m%d_%H%M%S"
                ).replace(tzinfo=timezone.utc)
                created_date = dt.isoformat()
            except ValueError:
                pass

        record = {
            "run_id": run_folder.name,
            "pr_id": pr_data["pr_id"],
            "department": pr_data["department"],
            "vendor_name": pr_data["vendor_name"],
            "item_id": first_item["item_id"],
            "total_amount": float(total_amount),
        }
        if created_date:
            record["created_date"] = created_date

        history.append(record)

    return history


def load_cost_center_authority(
    cost_center: str
) -> CostCenterAuthority | None:
    file_path = BASE_DIR / "data" / "sample_data" / "cost_center_mapping.csv"

    if not file_path.exists():
        return None

    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            if row["cost_center"] == cost_center:
                return CostCenterAuthority(
                    cost_center=row["cost_center"],
                    department=row["department"],
                    approver_role=row["approver_role"],
                    finance_owner=row["finance_owner"],
                    region=row["region"]
                )

    return None

def append_to_pr_history(pr_data: dict, final_result: dict, vendor_result: dict) -> None:
    """
    Write a completed pipeline run back into pr_history.csv
    so split-order detection has fresh data on the next run.
    """
    import csv
    from datetime import datetime, timezone

    file_path = BASE_DIR / "data" / "sample_data" / "pr_history.csv"

    line_items = pr_data.get("line_items", [])
    first_item_id = line_items[0].get("item_id") if line_items else ""
    total_amount = sum(
        float(item.get("quantity", 1)) * float(item.get("unit_price", 0))
        for item in line_items
    )

    row = {
        "pr_id": pr_data.get("pr_id", ""),
        "department": pr_data.get("department", ""),
        "vendor_name": pr_data.get("vendor_name", ""),
        "item_id": first_item_id,
        "total_amount": total_amount,
        "created_date": datetime.now(timezone.utc).isoformat(),
    }

    file_exists = file_path.exists()

    with open(file_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["pr_id", "department", "vendor_name", "item_id", "total_amount", "created_date"],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
