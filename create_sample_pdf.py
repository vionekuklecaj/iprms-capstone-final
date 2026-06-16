import fitz
from pathlib import Path


PDF_TEXT = """PR ID: PR-PDF-001
Requestor Name: John Smith
Department: IT
Cost Center: IT001
Business Justification: New employee laptops
Vendor Name: Dell Partner
Item ID: LAP-001
Description: Dell Latitude 5550
Quantity: 3
Unit Price: 1200
Currency: USD
"""


def create_pdf():
    output_dir = Path("data/pr_bundles")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "pr_sample.pdf"

    document = fitz.open()
    page = document.new_page()

    page.insert_text(
        (72, 72),
        PDF_TEXT,
        fontsize=12
    )

    document.save(output_path)
    document.close()

    print(f"Created sample PDF: {output_path}")


if __name__ == "__main__":
    create_pdf()