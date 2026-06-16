"""
CLI Demo — run a PDF (digital or scanned) through the pipeline.
Usage: python demo_pdf.py data/pr_bundles/pr_sample.pdf
"""

import sys
from pathlib import Path

from app.services.pdf_parser import parse_requisition_pdf, extract_text_from_pdf
from app.pipeline import run_pipeline


def run_pdf_demo(file_path: str):
    print(f"\nParsing PDF: {file_path}")

    _, method = extract_text_from_pdf(file_path)
    print(f"Extraction method: {method}")

    pr = parse_requisition_pdf(file_path)
    print(f"Extracted PR ID: {pr.pr_id}")
    print(f"Line items: {len(pr.line_items)}")

    result = run_pipeline(pr, input_source="PDF")
    final = result["final_result"]

    print(f"\nDecision:  {final['final_decision']}")
    print(f"Approver:  {final['approval_packet']['required_approver']}")
    print(f"Reason:    {final['approval_packet']['reason']}")

    exceptions = result["compliance"]["exceptions"]
    if exceptions:
        print(f"\nExceptions ({len(exceptions)}):")
        for exc in exceptions:
            print(f"  [{exc['severity']}] {exc['type']}")
    else:
        print("\nNo exceptions.")

    print(f"\nArtifacts: {result['run_artifacts'].get('run_directory', '—')}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python demo_pdf.py data/pr_bundles/pr_sample.pdf")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    run_pdf_demo(str(path))
