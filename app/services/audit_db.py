
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "runs" / "audit.db"


def _get_engine():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    # Enable WAL mode for concurrent reads
    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    return engine


_engine = _get_engine()
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class PipelineRun(Base):
    

    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(128), unique=True, nullable=False, index=True)
    pr_id = Column(String(64), nullable=False, index=True)
    run_directory = Column(String(512))
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)
    input_source = Column(String(64), default="JSON")  # JSON | PDF | WEB_FORM | OCR_PDF

    
    final_decision = Column(String(32))
    required_approver = Column(String(128))
    procurement_action = Column(String(64))
    overall_priority = Column(String(16))
    exception_count = Column(Integer, default=0)
    anomaly_detected = Column(Boolean, default=False)

    
    total_amount = Column(Float)
    available_budget = Column(Float)
    budget_status = Column(String(32))

    
    vendor_name = Column(String(128))
    vendor_status = Column(String(32))

    
    compliance_status = Column(String(32))

    
    exception_types_json = Column(Text)   
    narrative_summary = Column(Text)


class AgentStep(Base):
    

    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(128), nullable=False, index=True)
    pr_id = Column(String(64), nullable=False, index=True)
    agent_name = Column(String(128), nullable=False)
    agent_role = Column(String(64))          
    status = Column(String(32))              
    output_summary = Column(Text)
    executed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    duration_ms = Column(Integer)
    extra_json = Column(Text)                


class ExceptionRecord(Base):
    

    __tablename__ = "exceptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(128), nullable=False, index=True)
    pr_id = Column(String(64), nullable=False, index=True)
    exception_type = Column(String(128), nullable=False, index=True)
    severity = Column(String(16), nullable=False, index=True)
    category = Column(String(64))
    message = Column(Text)
    next_action = Column(Text)
    rule_reference = Column(String(64))
    raised_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))



Base.metadata.create_all(_engine)


def get_session() -> Session:
    return _SessionLocal()




def log_pipeline_run(
    *,
    run_id: str,
    pr_id: str,
    run_directory: str,
    input_source: str,
    budget_result: dict,
    vendor_result: dict,
    compliance_result: dict,
    final_result: dict,
    anomaly_result: dict | None = None,
) -> None:
    

    exception_types = [
        exc.get("type", "UNKNOWN")
        for exc in compliance_result.get("exceptions", [])
    ]

    approval_packet = final_result.get("approval_packet", {})

    with get_session() as session:
        run = PipelineRun(
            run_id=run_id,
            pr_id=pr_id,
            run_directory=run_directory,
            input_source=input_source,
            completed_at=datetime.now(timezone.utc),
            final_decision=final_result.get("final_decision"),
            required_approver=approval_packet.get("required_approver"),
            procurement_action=final_result.get("procurement_action"),
            overall_priority=final_result.get("overall_priority"),
            exception_count=len(exception_types),
            anomaly_detected=(
                anomaly_result.get("anomaly_detected", False)
                if anomaly_result else False
            ),
            total_amount=budget_result.get("requested_amount"),
            available_budget=budget_result.get("available_budget"),
            budget_status=budget_result.get("status"),
            vendor_name=vendor_result.get("requested_vendor"),
            vendor_status=vendor_result.get("vendor_status"),
            compliance_status=compliance_result.get("compliance_status"),
            exception_types_json=json.dumps(exception_types),
            narrative_summary=approval_packet.get("narrative_summary"),
        )
        session.add(run)

        
        audit_steps = final_result.get("audit_log", {}).get("steps", [])
        for step in audit_steps:
            session.add(AgentStep(
                run_id=run_id,
                pr_id=pr_id,
                agent_name=step.get("agent", "Unknown"),
                status=step.get("status", "COMPLETED"),
                output_summary=step.get("output", ""),
            ))

        
        for exc in compliance_result.get("exceptions", []):
            session.add(ExceptionRecord(
                run_id=run_id,
                pr_id=pr_id,
                exception_type=exc.get("type", "UNKNOWN"),
                severity=exc.get("severity", "LOW"),
                message=exc.get("message", ""),
                next_action=exc.get("next_action", ""),
                rule_reference=exc.get("rule_reference", ""),
            ))

        session.commit()


def log_agent_step(
    *,
    run_id: str,
    pr_id: str,
    agent_name: str,
    agent_role: str = "",
    status: str = "COMPLETED",
    output_summary: str = "",
    duration_ms: int | None = None,
    extra: dict | None = None,
) -> None:
    
    with get_session() as session:
        session.add(AgentStep(
            run_id=run_id,
            pr_id=pr_id,
            agent_name=agent_name,
            agent_role=agent_role,
            status=status,
            output_summary=output_summary,
            duration_ms=duration_ms,
            extra_json=json.dumps(extra) if extra else None,
        ))
        session.commit()




def get_recent_runs(limit: int = 20) -> list[dict]:
    
    with get_session() as session:
        rows = (
            session.query(PipelineRun)
            .order_by(PipelineRun.completed_at.desc())
            .limit(limit)
            .all()
        )
        return [_run_to_dict(r) for r in rows]


def get_run_by_id(run_id: str) -> dict | None:
    with get_session() as session:
        row = session.query(PipelineRun).filter_by(run_id=run_id).first()
        return _run_to_dict(row) if row else None


def get_exceptions_for_run(run_id: str) -> list[dict]:
    with get_session() as session:
        rows = session.query(ExceptionRecord).filter_by(run_id=run_id).all()
        return [_exc_to_dict(r) for r in rows]


def get_runs_for_pr(pr_id: str) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(PipelineRun)
            .filter_by(pr_id=pr_id)
            .order_by(PipelineRun.completed_at.desc())
            .all()
        )
        return [_run_to_dict(r) for r in rows]


def get_exception_summary() -> list[dict]:
    
    from sqlalchemy import func
    with get_session() as session:
        rows = (
            session.query(
                ExceptionRecord.exception_type,
                ExceptionRecord.severity,
                func.count(ExceptionRecord.id).label("count"),
            )
            .group_by(ExceptionRecord.exception_type, ExceptionRecord.severity)
            .order_by(func.count(ExceptionRecord.id).desc())
            .all()
        )
        return [
            {"exception_type": r.exception_type, "severity": r.severity, "count": r.count}
            for r in rows
        ]


def get_audit_stats() -> dict[str, Any]:
    
    from sqlalchemy import func
    with get_session() as session:
        total_runs = session.query(func.count(PipelineRun.id)).scalar() or 0
        approved = (
            session.query(func.count(PipelineRun.id))
            .filter(PipelineRun.final_decision == "APPROVED")
            .scalar() or 0
        )
        review_required = (
            session.query(func.count(PipelineRun.id))
            .filter(PipelineRun.final_decision == "REVIEW_REQUIRED")
            .scalar() or 0
        )
        anomalies = (
            session.query(func.count(PipelineRun.id))
            .filter(PipelineRun.anomaly_detected.is_(True))
            .scalar() or 0
        )
        avg_exceptions = (
            session.query(func.avg(PipelineRun.exception_count)).scalar() or 0.0
        )
        return {
            "total_runs": total_runs,
            "approved": approved,
            "review_required": review_required,
            "anomalies_detected": anomalies,
            "avg_exceptions_per_run": round(float(avg_exceptions), 2),
        }




def _run_to_dict(r: PipelineRun) -> dict:
    return {
        "run_id": r.run_id,
        "pr_id": r.pr_id,
        "run_directory": r.run_directory,
        "input_source": r.input_source,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "final_decision": r.final_decision,
        "required_approver": r.required_approver,
        "procurement_action": r.procurement_action,
        "overall_priority": r.overall_priority,
        "exception_count": r.exception_count,
        "anomaly_detected": r.anomaly_detected,
        "total_amount": r.total_amount,
        "available_budget": r.available_budget,
        "budget_status": r.budget_status,
        "vendor_name": r.vendor_name,
        "vendor_status": r.vendor_status,
        "compliance_status": r.compliance_status,
        "exception_types": json.loads(r.exception_types_json or "[]"),
        "narrative_summary": r.narrative_summary,
    }


def _exc_to_dict(r: ExceptionRecord) -> dict:
    return {
        "exception_type": r.exception_type,
        "severity": r.severity,
        "category": r.category,
        "message": r.message,
        "next_action": r.next_action,
        "rule_reference": r.rule_reference,
        "raised_at": r.raised_at.isoformat() if r.raised_at else None,
    }


def get_pr_data_for_rerun(run_id: str) -> Optional[dict]:
    
    import json
    run = get_run_by_id(run_id)
    if not run:
        return None

    run_dir = Path(run.get("run_directory", ""))
    extracted_pr_path = run_dir / "extracted_pr.json"

    if not extracted_pr_path.exists():
        return None

    with open(extracted_pr_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle both top-level and nested 'extracted_pr' keys
    pr_data = data.get("extracted_pr", data)
    return pr_data
