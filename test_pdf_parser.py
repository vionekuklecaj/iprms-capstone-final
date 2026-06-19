from app.services.pdf_parser import parse_requisition_pdf

pr = parse_requisition_pdf("data/pr_bundles/pr_sample.pdf")

print(pr.model_dump())