import fitz
from pathlib import Path


PDF_TEXT = """PR ID: PR-PDF-MULTI-001
Requestor Name: John Smith
Department: IT
Cost Center: IT001
Business Justification: Multi-item onboarding equipment
Vendor Name: Dell Partner

Line Items:

Item ID: LAP-001
Description: Dell Latitude 5550
Quantity: 2
Unit Price: 1200
Currency: USD

Item ID: MON-001
Description: Dell 24 inch Monitor
Quantity: 2
Unit Price: 250
Currency: USD
"""


def create_pdf():
    output_dir = Path("data/pr_bundles")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "pr_multi_item.pdf"

    document = fitz.open()
    page = document.new_page()

    page.insert_text(
        (72, 72),
        PDF_TEXT,
        fontsize=12
    )

    document.save(output_path)
    document.close()

    print(f"Created multi-item PDF: {output_path}")


if __name__ == "__main__":
    create_pdf()