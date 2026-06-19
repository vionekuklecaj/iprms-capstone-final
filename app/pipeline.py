
from __future__ import annotations

from typing import TypedDict, Optional, Any

from langgraph.graph import StateGraph, END

from app.schemas.purchase_requisition import PurchaseRequisition
from app.schemas.context import ContextPacket
from app.agents.intake_agent import IntakeAgent
from app.agents.budget_agent import BudgetAgent
from app.agents.vendor_agent import VendorAgent
from app.agents.anomaly_agent import AnomalyAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.orchestrator_agent import OrchestratorAgent
from app.agents.vendor_risk_agent import VendorRiskAgent
from app.agents.pr_classification_agent import PRClassificationAgent
from app.services.artifact_writer import save_run_artifacts




class PipelineState(TypedDict):
    
    pr: PurchaseRequisition
    input_source: str

    
    context_packet: Optional[ContextPacket]
    classification_result: Optional[dict]
    budget_result: Optional[dict]
    vendor_result: Optional[dict]
    vendor_risk_result: Optional[dict]
    anomaly_result: Optional[dict]
    compliance_result: Optional[dict]
    final_result: Optional[dict]
    run_artifacts: Optional[dict]

    
    errors: list[str]




def node_intake(state: PipelineState) -> PipelineState:
    
    try:
        
        classification_agent = PRClassificationAgent()
        classification_detail = classification_agent.classify(state["pr"])

        
        intake = IntakeAgent()
        ctx = intake.run(state["pr"])

        
        if classification_detail.get("assessment_method") == "llm_langchain":
            from app.schemas.context import RequestClassification
            ctx = ctx.model_copy(update={
                "classification": RequestClassification(
                    request_type=classification_detail.get("request_type", "GENERAL_PURCHASE"),
                    priority=classification_detail.get("priority", "STANDARD"),
                    confidence=float(classification_detail.get("confidence", 0.70)),
                    reason=classification_detail.get("reason", "LLM classification."),
                )
            })

        return {
            **state,
            "context_packet": ctx,
            "classification_result": classification_detail,
        }
    except Exception as e:
        return {**state, "errors": state.get("errors", []) + [f"intake: {e}"]}


def node_budget(state: PipelineState) -> PipelineState:
    
    try:
        result = BudgetAgent().run(state["context_packet"])
        return {**state, "budget_result": result}
    except Exception as e:
        return {**state, "errors": state.get("errors", []) + [f"budget: {e}"]}


def node_vendor(state: PipelineState) -> PipelineState:
    
    try:
        result = VendorAgent().run(state["context_packet"])
        return {**state, "vendor_result": result}
    except Exception as e:
        return {**state, "errors": state.get("errors", []) + [f"vendor: {e}"]}


def node_vendor_risk(state: PipelineState) -> PipelineState:
    
    try:
        result = VendorRiskAgent().run(state["context_packet"], state["vendor_result"])
        return {**state, "vendor_risk_result": result}
    except Exception as e:
        return {
            **state,
            "vendor_risk_result": {"error": str(e), "assessment_method": "failed"},
            "errors": state.get("errors", []) + [f"vendor_risk: {e}"],
        }


def node_anomaly(state: PipelineState) -> PipelineState:
    
    try:
        result = AnomalyAgent().run(state["context_packet"])
        return {**state, "anomaly_result": result}
    except Exception as e:
        return {
            **state,
            "anomaly_result": {"anomaly_detected": False, "error": str(e)},
            "errors": state.get("errors", []) + [f"anomaly: {e}"],
        }


def node_compliance(state: PipelineState) -> PipelineState:
    
    try:
        result = ComplianceAgent().run(
            state["context_packet"],
            state["budget_result"],
            state["vendor_result"],
            state["anomaly_result"],
        )
        return {**state, "compliance_result": result}
    except Exception as e:
        return {**state, "errors": state.get("errors", []) + [f"compliance: {e}"]}


def node_orchestrate(state: PipelineState) -> PipelineState:
    
    try:
        result = OrchestratorAgent().run(
            state["context_packet"],
            state["budget_result"],
            state["vendor_result"],
            state["compliance_result"],
        )

        
        if state.get("vendor_risk_result"):
            result["vendor_risk_assessment"] = state["vendor_risk_result"]

        
        if state.get("classification_result"):
            result["classification_detail"] = state["classification_result"]

        return {**state, "final_result": result}
    except Exception as e:
        return {**state, "errors": state.get("errors", []) + [f"orchestrate: {e}"]}


def node_save_artifacts(state: PipelineState) -> PipelineState:
    
    try:
        pr = state["pr"]
        ctx = state["context_packet"]

        run_artifacts = save_run_artifacts(
            pr_id=pr.pr_id,
            context_packet=ctx.model_dump(),
            budget_result=state["budget_result"],
            vendor_result=state["vendor_result"],
            compliance_result=state["compliance_result"],
            final_result=state["final_result"],
            anomaly_result=state["anomaly_result"],
            input_source=state.get("input_source", "JSON"),
        )
        return {**state, "run_artifacts": run_artifacts}
    except Exception as e:
        return {**state, "errors": state.get("errors", []) + [f"artifacts: {e}"]}




def should_continue_after_intake(state: PipelineState) -> str:
    
    if state.get("context_packet") is None:
        return "end"
    return "budget"




def build_pipeline_graph() -> StateGraph:
    
    graph = StateGraph(PipelineState)

    
    graph.add_node("intake", node_intake)
    graph.add_node("budget", node_budget)
    graph.add_node("vendor", node_vendor)
    graph.add_node("vendor_risk", node_vendor_risk)
    graph.add_node("anomaly", node_anomaly)
    graph.add_node("compliance", node_compliance)
    graph.add_node("orchestrate", node_orchestrate)
    graph.add_node("save_artifacts", node_save_artifacts)

    
    graph.set_entry_point("intake")

    
    graph.add_conditional_edges(
        "intake",
        should_continue_after_intake,
        {"budget": "budget", "end": END},
    )
    graph.add_edge("budget", "vendor")
    graph.add_edge("vendor", "vendor_risk")
    graph.add_edge("vendor_risk", "anomaly")
    graph.add_edge("anomaly", "compliance")
    graph.add_edge("compliance", "orchestrate")
    graph.add_edge("orchestrate", "save_artifacts")
    graph.add_edge("save_artifacts", END)

    return graph.compile()




_graph = None


def get_pipeline():
    global _graph
    if _graph is None:
        _graph = build_pipeline_graph()
    return _graph


def run_pipeline(pr: PurchaseRequisition, input_source: str = "JSON") -> dict:
    
    pipeline = get_pipeline()

    initial_state: PipelineState = {
        "pr": pr,
        "input_source": input_source,
        "context_packet": None,
        "classification_result": None,
        "budget_result": None,
        "vendor_result": None,
        "vendor_risk_result": None,
        "anomaly_result": None,
        "compliance_result": None,
        "final_result": None,
        "run_artifacts": None,
        "errors": [],
    }

    final_state = pipeline.invoke(initial_state)

    return {
        "message": "Pipeline completed successfully",
        "context_packet": final_state["context_packet"].model_dump() if final_state.get("context_packet") else {},
        "budget_check": final_state.get("budget_result", {}),
        "vendor_match": final_state.get("vendor_result", {}),
        "vendor_risk": final_state.get("vendor_risk_result", {}),
        "anomaly_check": final_state.get("anomaly_result", {}),
        "compliance": final_state.get("compliance_result", {}),
        "final_result": final_state.get("final_result", {}),
        "run_artifacts": final_state.get("run_artifacts", {}),
        "pipeline_errors": final_state.get("errors", []),
        "classification_detail": final_state.get("classification_result", {}),
    }
