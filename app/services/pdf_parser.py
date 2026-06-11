"""
PDF Parser with OCR Support
============================
Handles both born-digital PDFs (via PyMuPDF) and scanned/image PDFs
(via pytesseract + PyMuPDF). Automatically detects which path to use
based on text yield from the digital extraction attempt.

Technologies: PyMuPDF (fitz), pytesseract, Pillow — no Poppler required
"""

from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from app.schemas.purchase_requisition import PurchaseRequisition, PRLineItem

# Windows: tell pytesseract where tesseract.exe lives
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Minimum characters on a page before we consider it "digital" (not scanned)
# ---------------------------------------------------------------------------
_DIGITAL_TEXT_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Low-level text extraction
# ---------------------------------------------------------------------------

def _extract_text_digital(file_path: str) -> str:
    """Extract text from a born-digital PDF using PyMuPDF."""
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def _extract_text_ocr(file_path: str) -> str:
    """
    Extract text from a scanned/image PDF using PyMuPDF (page → image)
    + pytesseract. No Poppler or pdf2image required — PyMuPDF handles
    the rendering natively on all platforms including Windows.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        doc = fitz.open(file_path)
        text_parts = []
        for page in doc:
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            page_text = pytesseract.image_to_string(img, lang="eng")
            text_parts.append(page_text)
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        return f"OCR_ERROR: {e}"


def extract_text_from_pdf(file_path: str) -> tuple[str, str]:
    """
    Smart extraction: tries digital first, falls back to OCR if text yield
    is too low (indicating a scanned document).

    Returns (text, method) where method is "digital" or "ocr".
    """
    digital_text = _extract_text_digital(file_path)
    meaningful_chars = len(re.sub(r"\s+", "", digital_text))

    if meaningful_chars >= _DIGITAL_TEXT_THRESHOLD:
        return digital_text, "digital"

    ocr_text = _extract_text_ocr(file_path)
    if ocr_text and not ocr_text.startswith("OCR_ERROR"):
        return ocr_text, "ocr"

    return digital_text or ocr_text, "digital_fallback"


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _get_value(text: str, field_name: str, default: Optional[str] = None) -> str:
    pattern = re.compile(
        rf"^{re.escape(field_name)}\s*:\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    if default is not None:
        return default
    raise ValueError(f"Missing field in PDF: {field_name}")


def _get_value_optional(text: str, field_name: str) -> Optional[str]:
    try:
        return _get_value(text, field_name)
    except ValueError:
        return None


def extract_field_evidence(file_path: str, field_values: dict) -> list[dict]:
    """Build bounding-box evidence for fields found in a digital PDF."""
    doc = fitz.open(file_path)
    evidence = []
    for page_index, page in enumerate(doc):
        for field_name, value in field_values.items():
            if value is None:
                continue
            matches = page.search_for(str(value))
            for match in matches:
                evidence.append({
                    "field": field_name,
                    "value": str(value),
                    "page": page_index + 1,
                    "bbox": [
                        round(match.x0, 2),
                        round(match.y0, 2),
                        round(match.x1, 2),
                        round(match.y1, 2),
                    ],
                })
                break
    doc.close()
    return evidence


# ---------------------------------------------------------------------------
# Line item parsing
# ---------------------------------------------------------------------------

def parse_line_items(text: str) -> list[PRLineItem]:
    lines = text.splitlines()
    line_items: list[PRLineItem] = []
    current_item: dict = {}

    item_fields = {
        "Item ID": "item_id",
        "Description": "description",
        "Quantity": "quantity",
        "Unit Price": "unit_price",
        "Currency": "currency",
    }

    for line in lines:
        for label, key in item_fields.items():
            pattern = re.compile(
                rf"^{re.escape(label)}\s*:\s*(.+)$", re.IGNORECASE
            )
            m = pattern.match(line.strip())
            if m:
                current_item[key] = m.group(1).strip()
                if key == "currency" and len(current_item) >= 5:
                    try:
                        line_items.append(
                            PRLineItem(
                                item_id=current_item.get("item_id"),
                                description=current_item["description"],
                                quantity=int(re.sub(r"[^\d]", "", current_item.get("quantity", "1")) or "1"),
                                unit_price=float(re.sub(r"[^\d.]", "", current_item.get("unit_price", "0")) or "0"),
                                currency=current_item["currency"].upper()[:3],
                            )
                        )
                    except (ValueError, KeyError):
                        pass
                    current_item = {}

    if line_items:
        return line_items

    try:
        return [
            PRLineItem(
                item_id=_get_value_optional(text, "Item ID"),
                description=_get_value(text, "Description"),
                quantity=int(re.sub(r"[^\d]", "", _get_value(text, "Quantity")) or "1"),
                unit_price=float(re.sub(r"[^\d.]", "", _get_value(text, "Unit Price")) or "0"),
                currency=_get_value(text, "Currency", "USD").upper()[:3],
            )
        ]
    except ValueError:
        return [
            PRLineItem(
                item_id="UNK-001",
                description="Unknown item extracted from PDF",
                quantity=1,
                unit_price=0.0,
                currency="USD",
            )
        ]


# ---------------------------------------------------------------------------
# Public parse API
# ---------------------------------------------------------------------------

def parse_requisition_pdf(file_path: str) -> PurchaseRequisition:
    text, method = extract_text_from_pdf(file_path)
    line_items = parse_line_items(text)

    raw_pr_dict = {
        "pr_id": _get_value(text, "PR ID", "PR-PDF-001"),
        "requestor_name": _get_value(text, "Requestor Name", "Unknown"),
        "department": _get_value(text, "Department", "Unknown"),
        "cost_center": _get_value(text, "Cost Center", "IT001"),
        "business_justification": _get_value(text, "Business Justification", "Extracted from PDF"),
        "vendor_name": _get_value_optional(text, "Vendor Name"),
        "gl_account": _get_value_optional(text, "GL Account"),
        "spend_type": _get_value(text, "Spend Type", "OPEX"),
        "procurement_type": _get_value(text, "Procurement Type", "STANDARD"),
        "contract_reference": _get_value_optional(text, "Contract Reference"),
        "emergency_reason": _get_value_optional(text, "Emergency Reason"),
        "quotes_received": int(re.sub(r"[^\d]", "", _get_value(text, "Quotes Received", "0")) or "0"),
        "sole_source_requested": (_get_value(text, "Sole Source Requested", "false").lower() == "true"),
        "sole_source_justification": _get_value_optional(text, "Sole Source Justification"),
        "line_items": [item.model_dump() for item in line_items],
    }

    ocr_corrections = []
    if method == "ocr":
        try:
            from app.services.ocr_corrector import apply_ocr_corrections
            from app.services.data_loader import load_approved_vendors
            known_vendors = [v.vendor_name for v in load_approved_vendors()]
            raw_pr_dict, ocr_corrections = apply_ocr_corrections(raw_pr_dict, known_vendors)
        except Exception:
            pass

    from app.schemas.purchase_requisition import PRLineItem
    pr_line_items = [PRLineItem(**item) for item in raw_pr_dict.pop("line_items")]

    pr = PurchaseRequisition(**raw_pr_dict, line_items=pr_line_items)
    pr.__dict__["_ocr_corrections"] = ocr_corrections
    return pr


def parse_requisition_pdf_with_evidence(file_path: str) -> dict:
    text, method = extract_text_from_pdf(file_path)
    pr = parse_requisition_pdf(file_path)

    field_evidence: list[dict] = []
    if method == "digital":
        field_values = {
            "pr_id": pr.pr_id,
            "requestor_name": pr.requestor_name,
            "department": pr.department,
            "cost_center": pr.cost_center,
            "business_justification": pr.business_justification,
            "vendor_name": pr.vendor_name,
        }
        if pr.line_items:
            first = pr.line_items[0]
            field_values.update({
                "item_id": first.item_id,
                "description": first.description,
                "quantity": str(first.quantity),
                "unit_price": str(first.unit_price),
                "currency": first.currency,
            })
        field_evidence = extract_field_evidence(file_path, field_values)

    return {
        "purchase_requisition": pr,
        "extraction_method": method,
        "field_evidence": field_evidence,
        "ocr_used": method == "ocr",
    }


# ---------------------------------------------------------------------------
# LLM-powered flexible extraction (any PDF layout)
# ---------------------------------------------------------------------------

def parse_requisition_pdf_flexible(file_path: str) -> tuple["PurchaseRequisition", dict]:
    """
    LLM-powered extraction — works on any PDF layout, not just
    'Field Name: value' formatted documents.
    """
    text, method = extract_text_from_pdf(file_path)

    if not text.strip():
        raise ValueError("Could not extract any text from PDF (empty result)")

    try:
        import json as _json
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

        prompt = f"""Extract purchase requisition fields from the following document text.
Return ONLY a valid JSON object with these exact keys (use null for missing fields):

{{
  "pr_id": "string",
  "requestor_name": "string",
  "department": "string",
  "cost_center": "string",
  "business_justification": "string",
  "vendor_name": "string or null",
  "gl_account": "string or null",
  "spend_type": "OPEX or CAPEX",
  "procurement_type": "STANDARD or EMERGENCY or FRAMEWORK_AGREEMENT or BLANKET_ORDER or SOLE_SOURCE",
  "quotes_received": 0,
  "sole_source_requested": false,
  "sole_source_justification": "string or null",
  "line_items": [
    {{
      "item_id": "string or null",
      "description": "string",
      "quantity": 1,
      "unit_price": 0.0,
      "currency": "USD"
    }}
  ]
}}

Document text:
{text[:4000]}

Return ONLY the JSON object, no explanation."""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_json = response.content[0].text.strip()
        raw_json = re.sub(r"^```(?:json)?", "", raw_json).strip()
        raw_json = re.sub(r"```$", "", raw_json).strip()

        pr_data = _json.loads(raw_json)

        ocr_corrections = []
        if method == "ocr":
            from app.services.ocr_corrector import apply_ocr_corrections
            from app.services.data_loader import load_approved_vendors
            known_vendors = [v.vendor_name for v in load_approved_vendors()]
            pr_data, ocr_corrections = apply_ocr_corrections(pr_data, known_vendors)

        line_items = []
        for item in pr_data.get("line_items", []):
            try:
                line_items.append(PRLineItem(
                    item_id=item.get("item_id"),
                    description=item.get("description", "Unknown"),
                    quantity=int(item.get("quantity", 1) or 1),
                    unit_price=float(item.get("unit_price", 0) or 0),
                    currency=(item.get("currency") or "USD").upper()[:3],
                ))
            except Exception:
                pass

        if not line_items:
            line_items = [PRLineItem(
                item_id="UNK-001",
                description="Unknown item (LLM extraction)",
                quantity=1,
                unit_price=0.0,
                currency="USD",
            )]

        pr = PurchaseRequisition(
            pr_id=pr_data.get("pr_id") or "PR-PDF-001",
            requestor_name=pr_data.get("requestor_name") or "Unknown",
            department=pr_data.get("department") or "Unknown",
            cost_center=pr_data.get("cost_center") or "IT001",
            business_justification=pr_data.get("business_justification") or "Extracted from PDF",
            vendor_name=pr_data.get("vendor_name"),
            gl_account=pr_data.get("gl_account"),
            spend_type=pr_data.get("spend_type") or "OPEX",
            procurement_type=pr_data.get("procurement_type") or "STANDARD",
            quotes_received=int(pr_data.get("quotes_received") or 0),
            sole_source_requested=bool(pr_data.get("sole_source_requested", False)),
            sole_source_justification=pr_data.get("sole_source_justification"),
            line_items=line_items,
        )

        return pr, {
            "method": method,
            "llm_used": True,
            "ocr_corrections": ocr_corrections,
        }

    except Exception as e:
        pr = parse_requisition_pdf(file_path)
        return pr, {
            "method": method,
            "llm_used": False,
            "llm_error": str(e),
            "ocr_corrections": getattr(pr.__dict__, "_ocr_corrections", []),
        }