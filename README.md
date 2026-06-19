# IPRMS — Intelligent Purchase Requisition Management System


---



### 2 New LLM-Powered Agents

**Agent B — PR Classification Agent** (`app/agents/pr_classification_agent.py`)
- Replaces simple keyword matching with LangChain + CrewAI intelligence
- Detects nuanced procurement risk signals (split patterns, unusual justifications)
- Infers GL account and suggests appropriate procurement paths
- Falls back to deterministic rules when no API key is set

**Agent F — Vendor Risk Analyst** (`app/agents/vendor_risk_agent.py`)
- LLM-powered risk scoring (1–10) with narrative explanation
- Determines whether additional due diligence is required
- Recommends PROCEED / ADDITIONAL_REVIEW / ESCALATE
- Falls back to rule-based scoring when no API key is set




## Architecture

```
PR Input (JSON / Web Form / PDF / Scanned PDF)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph StateGraph Pipeline           │
│                                                     │
│  intake ──► budget ──► vendor ──► vendor_risk       │
│    (A+B)     (C)        (D)          (F) LLM        │
│                                         │           │
│                                         ▼           │
│  save_artifacts ◄── orchestrate ◄── compliance      │
│        │               (H)            (E)           │
│        ▼                                            │
│   SQLite Audit DB + run artifacts/                  │
└─────────────────────────────────────────────────────┘
```

**Agent roles:**
- **Agent A** — Intake & Context (data loading, evidence index)
- **Agent B** — PR Classification (LLM-powered via LangChain + CrewAI)
- **Agent C** — Budget Validation (deterministic)
- **Agent D** — Vendor Matching (deterministic)
- **Agent F** — Vendor Risk Analyst (LLM-powered via LangChain + CrewAI)  ← NEW
- **Anomaly** — Split Order Detection (time-windowed, fixed)
- **Agent E** — Compliance & Policy Engine (deterministic)
- **Agent H** — Lead Orchestrator (deterministic + AI narrative summary)

---



## File Structure

```
iprms-master/
├── app/
│   ├── agents/
│   │   ├── intake_agent.py          # Agent A (uses PRClassificationAgent)
│   │   ├── budget_agent.py          # Agent C
│   │   ├── vendor_agent.py          # Agent D
│   │   ├── vendor_risk_agent.py     # Agent F — NEW (LangChain + CrewAI)
│   │   ├── pr_classification_agent.py # Agent B — NEW (LangChain + CrewAI)
│   │   ├── anomaly_agent.py         # Fixed: time-windowed split-order
│   │   ├── compliance_agent.py      # Agent E
│   │   └── orchestrator_agent.py    # Agent H
│   ├── pipeline.py                  # NEW — LangGraph StateGraph pipeline
│   ├── services/
│   │   ├── audit_db.py             # NEW — SQLAlchemy audit database
│   │   ├── pdf_parser.py            # Enhanced: OCR + robust parsing
│   │   ├── artifact_writer.py       # Enhanced: calls audit DB
│   │   ├── summary_writer.py        # AI narrative summary
│   │   └── data_loader.py
│   ├── schemas/
│   │   ├── context.py
│   │   └── purchase_requisition.py
│   └── main.py                      # FastAPI + audit endpoints
├── ui.py                            # Streamlit UI (fixed + enhanced)
├── runs/
│   └── audit.db                     # SQLite audit database
├── data/
│   ├── pr_bundles/                  # 22 test scenarios
│   └── sample_data/
├── policies/
│   └── policy.yaml
└── requirements.txt                 # Updated with new dependencies
```
