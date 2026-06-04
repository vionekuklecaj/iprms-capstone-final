from app.schemas.context import ContextPacket
from app.services.data_loader import load_policy


class VendorAgent:
    """
    Agent D - Vendor Matching

    """

    def run(self, context: ContextPacket) -> dict:
        policy = load_policy()

        catalogue_price_tolerance_percent = policy.get(
            "tolerance_percentages",
            {}
        ).get(
            "catalogue_price_tolerance_percent",
            0
        )

        requested_vendor = context.pr.vendor_name

        if requested_vendor is None:
            return {
                "requested_vendor": None,
                "vendor_status": "MISSING",
                "vendor_reason": "No vendor was provided in the requisition",
                "vendor_risk": "UNKNOWN",
                "supplier_selection_status": "INVALID",
                "catalogue_price_tolerance_percent": catalogue_price_tolerance_percent,
                "price_tolerance_issues": [],
                "preferred_vendor_issues": [],
                "matched_items": []
            }

        vendor_record = None

        for vendor in context.approved_vendors:
            if vendor.vendor_name.lower() == requested_vendor.lower():
                vendor_record = vendor
                break

        if vendor_record is None:
            vendor_status = "NOT_FOUND"
            vendor_reason = "Requested vendor was not found in approved vendor list"
            vendor_risk = "UNKNOWN"
        elif vendor_record.status == "APPROVED":
            vendor_status = "APPROVED"
            vendor_reason = "Requested vendor is approved"
            vendor_risk = vendor_record.risk_level
        else:
            vendor_status = "NOT_APPROVED"
            vendor_reason = "Requested vendor is listed but not approved"
            vendor_risk = vendor_record.risk_level

        matched_items = []
        preferred_vendor_issues = []
        price_tolerance_issues = []

        for pr_item in context.pr.line_items:
            catalog_match = None

            for catalog_item in context.catalog_items:
                if catalog_item.item_id == pr_item.item_id:
                    catalog_match = catalog_item
                    break

            if catalog_match:
                preferred_vendor = catalog_match.approved_vendor
                preferred_vendor_match = (
                    requested_vendor.lower() == preferred_vendor.lower()
                )

                catalog_price = catalog_item.unit_price
                requested_price = pr_item.unit_price
                price_difference = requested_price - catalog_price

                if catalog_price > 0:
                    price_difference_percent = (
                        price_difference / catalog_price
                    ) * 100
                else:
                    price_difference_percent = 0

                price_within_tolerance = (
                    abs(price_difference_percent)
                    <= catalogue_price_tolerance_percent
                )

                if not price_within_tolerance:
                    price_tolerance_issues.append({
                        "item_id": pr_item.item_id,
                        "description": pr_item.description,
                        "catalog_unit_price": catalog_price,
                        "requested_unit_price": requested_price,
                        "price_difference": price_difference,
                        "price_difference_percent": round(price_difference_percent, 2),
                        "allowed_tolerance_percent": catalogue_price_tolerance_percent,
                        "message": "Requested unit price is outside allowed catalogue price tolerance"
                    })

                if not preferred_vendor_match:
                    preferred_vendor_issues.append({
                        "item_id": pr_item.item_id,
                        "description": pr_item.description,
                        "requested_vendor": requested_vendor,
                        "preferred_vendor": preferred_vendor,
                        "message": "Requested vendor is approved generally but is not the preferred catalogue vendor for this item"
                    })

                matched_items.append({
                    "item_id": pr_item.item_id,
                    "description": pr_item.description,
                    "catalog_match": True,
                    "catalog_unit_price": catalog_price,
                    "requested_unit_price": requested_price,
                    "price_difference": price_difference,
                    "price_difference_percent": round(price_difference_percent, 2),
                    "catalogue_price_tolerance_percent": catalogue_price_tolerance_percent,
                    "price_within_tolerance": price_within_tolerance,
                    "preferred_vendor": preferred_vendor,
                    "requested_vendor": requested_vendor,
                    "preferred_vendor_match": preferred_vendor_match,
                    "supplier_selection": (
                        "PREFERRED"
                        if preferred_vendor_match
                        else "NON_PREFERRED"
                    )
                })
            else:
                matched_items.append({
                    "item_id": pr_item.item_id,
                    "description": pr_item.description,
                    "catalog_match": False,
                    "reason": "Item not found in catalogue"
                })

        if vendor_status != "APPROVED":
            supplier_selection_status = "INVALID_VENDOR"
        elif preferred_vendor_issues:
            supplier_selection_status = "NON_PREFERRED_APPROVED_VENDOR"
        elif price_tolerance_issues:
            supplier_selection_status = "PRICE_OUTSIDE_TOLERANCE"
        else:
            supplier_selection_status = "PREFERRED_VENDOR"

        return {
            "requested_vendor": requested_vendor,
            "vendor_status": vendor_status,
            "vendor_reason": vendor_reason,
            "vendor_risk": vendor_risk,
            "supplier_selection_status": supplier_selection_status,
            "catalogue_price_tolerance_percent": catalogue_price_tolerance_percent,
            "price_tolerance_issues": price_tolerance_issues,
            "preferred_vendor_issues": preferred_vendor_issues,
            "matched_items": matched_items
        }