
from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Optional



KNOWN_COST_CENTERS = ["IT001", "HR001", "FIN001", "OPS001", "ENG001"]
KNOWN_SPEND_TYPES = ["OPEX", "CAPEX"]
KNOWN_PROCUREMENT_TYPES = [
    "STANDARD", "EMERGENCY", "FRAMEWORK_AGREEMENT",
    "BLANKET_ORDER", "SOLE_SOURCE"
]
KNOWN_DEPARTMENTS = ["IT", "HR", "Finance", "Operations", "Engineering"]


_CHAR_FIXES = {
    "0": "O",  
    "1": "I",
    "l": "I",
    "|": "I",
    "Q": "O",  
}


def _normalize_ocr_token(token: str) -> str:
    
    result = list(token)
    for i, ch in enumerate(result):
        if ch in _CHAR_FIXES:
            result[i] = _CHAR_FIXES[ch]
    return "".join(result)


def _best_match(value: str, candidates: list[str], cutoff: float = 0.6) -> Optional[str]:
    
    if not value:
        return None

    
    upper = value.upper().strip()
    for c in candidates:
        if c.upper() == upper:
            return c

    
    normalized = _normalize_ocr_token(upper)
    for c in candidates:
        if c.upper() == normalized:
            return c

    
    matches = get_close_matches(upper, [c.upper() for c in candidates], n=1, cutoff=cutoff)
    if matches:
        idx = [c.upper() for c in candidates].index(matches[0])
        return candidates[idx]

    return None


def correct_cost_center(raw: str) -> tuple[str, bool]:
    """Returns (corrected_value, was_corrected)."""
    if not raw:
        return raw, False
    match = _best_match(raw, KNOWN_COST_CENTERS, cutoff=0.5)
    if match and match != raw:
        return match, True
    return raw, False


def correct_spend_type(raw: str) -> tuple[str, bool]:
    if not raw:
        return raw, False
    match = _best_match(raw, KNOWN_SPEND_TYPES, cutoff=0.7)
    if match and match != raw:
        return match, True
    return raw, False


def correct_procurement_type(raw: str) -> tuple[str, bool]:
    if not raw:
        return raw, False
    match = _best_match(raw, KNOWN_PROCUREMENT_TYPES, cutoff=0.6)
    if match and match != raw:
        return match, True
    return raw, False


def correct_vendor_name(raw: str, known_vendors: list[str]) -> tuple[str, bool]:
    if not raw or not known_vendors:
        return raw, False
    match = _best_match(raw, known_vendors, cutoff=0.7)
    if match and match != raw:
        return match, True
    return raw, False


def apply_ocr_corrections(pr_data: dict, known_vendors: list[str]) -> tuple[dict, list[str]]:
    
    corrections = []
    pr = dict(pr_data)

    
    if "cost_center" in pr:
        corrected, changed = correct_cost_center(pr["cost_center"])
        if changed:
            corrections.append(f"cost_center: '{pr['cost_center']}' → '{corrected}'")
            pr["cost_center"] = corrected

    
    if "spend_type" in pr:
        corrected, changed = correct_spend_type(pr["spend_type"])
        if changed:
            corrections.append(f"spend_type: '{pr['spend_type']}' → '{corrected}'")
            pr["spend_type"] = corrected

    
    if "procurement_type" in pr:
        corrected, changed = correct_procurement_type(pr["procurement_type"])
        if changed:
            corrections.append(f"procurement_type: '{pr['procurement_type']}' → '{corrected}'")
            pr["procurement_type"] = corrected

    
    if "vendor_name" in pr and pr["vendor_name"]:
        corrected, changed = correct_vendor_name(pr["vendor_name"], known_vendors)
        if changed:
            corrections.append(f"vendor_name: '{pr['vendor_name']}' → '{corrected}'")
            pr["vendor_name"] = corrected

    
    if "line_items" in pr:
        for i, item in enumerate(pr["line_items"]):
            if "item_id" in item and item["item_id"]:
                raw_id = item["item_id"]
                # Only apply char-level fix to item IDs (no fuzzy — too many possibilities)
                fixed = _normalize_ocr_token(raw_id.upper())
                # Re-apply lowercase letters for mixed IDs like "LAP-001"
                if fixed != raw_id:
                    corrections.append(f"line_items[{i}].item_id: '{raw_id}' → '{fixed}'")
                    pr["line_items"][i] = {**item, "item_id": fixed}

    return pr, corrections
