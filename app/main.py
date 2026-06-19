
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
import tempfile

from app.pipeline import run_pipeline
from app.schemas.purchase_requisition import PurchaseRequisition
from app.services.audit_db import (
    get_recent_runs,
    get_run_by_id,
    get_exceptions_for_run,
    get_audit_stats,
    get_exception_summary,
    get_pr_data_for_rerun,
)
from app.services.export_service import runs_to_csv, exceptions_to_csv, audit_stats_to_csv
from fastapi.responses import StreamingResponse
import io

_API_KEY = os.environ.get("IPRMS_API_KEY", "iprms-dev-key")


def _verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


app = FastAPI(
    title="IPRMS",
    description="Intelligent Purchase Requisition Management System",
    version="3.0.0",
)


@app.get("/")
def root():
    return {
        "project": "IPRMS",
        "version": "3.0.0",
        "status": "running",
        "pipeline": "LangGraph",
        "auth": "X-API-Key header required",
    }


@app.post("/pipeline/run", dependencies=[Depends(_verify_api_key)])
def run_pipeline_endpoint(pr: PurchaseRequisition):
    
    return run_pipeline(pr, input_source="JSON")


@app.post("/pipeline/run-pdf", dependencies=[Depends(_verify_api_key)])
async def run_pipeline_pdf(file: UploadFile = File(...)):
    
    from app.services.pdf_parser import parse_requisition_pdf_flexible
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        pr, meta = parse_requisition_pdf_flexible(tmp_path)
        result = run_pipeline(pr, input_source="PDF")
        result["pdf_extraction_meta"] = meta
        return result
    finally:
        import os as _os
        _os.unlink(tmp_path)


@app.post("/pipeline/rerun/{run_id}", dependencies=[Depends(_verify_api_key)])
def rerun_pipeline(run_id: str):
    
    pr_data = get_pr_data_for_rerun(run_id)
    if not pr_data:
        raise HTTPException(status_code=404, detail="Run not found or PR data unavailable")
    try:
        pr = PurchaseRequisition(**pr_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid PR data in run: {e}")
    return run_pipeline(pr, input_source="RERUN")




@app.get("/audit/runs", dependencies=[Depends(_verify_api_key)])
def list_runs(limit: int = 20):
    return {"runs": get_recent_runs(limit=limit)}


@app.get("/audit/runs/{run_id}", dependencies=[Depends(_verify_api_key)])
def get_run(run_id: str):
    run = get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    exceptions = get_exceptions_for_run(run_id)
    return {"run": run, "exceptions": exceptions}


@app.get("/audit/stats", dependencies=[Depends(_verify_api_key)])
def audit_stats():
    return {
        "stats": get_audit_stats(),
        "exception_summary": get_exception_summary(),
    }




@app.get("/export/runs.csv", dependencies=[Depends(_verify_api_key)])
def export_runs_csv(limit: int = 200):
    data = runs_to_csv(get_recent_runs(limit=limit))
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=iprms_runs.csv"},
    )


@app.get("/export/stats.csv", dependencies=[Depends(_verify_api_key)])
def export_stats_csv():
    stats = get_audit_stats()
    exc_summary = get_exception_summary()
    data = audit_stats_to_csv(stats, exc_summary)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=iprms_stats.csv"},
    )
