# IPRMS — Intelligent Purchase Requisition Management System
## v2.0 — Enhanced Multi-Agent Procurement Pipeline

---

## What's New in v2.0

### 5 New Technologies

| Technology | Role | Where |
|---|---|---|
| **LangGraph** | Stateful multi-agent pipeline (StateGraph) | `app/pipeline.py` |
| **LangChain** | LLM chains, prompt templates, JSON output parsers | `app/agents/vendor_risk_agent.py`, `app/agents/pr_classification_agent.py` |
| **CrewAI** | Agent role/persona definitions for LLM agents | `app/agents/vendor_risk_agent.py`, `app/agents/pr_classification_agent.py` |
| **pytesseract + pdf2image** | OCR for scanned PDFs (auto-detected fallback) | `app/services/pdf_parser.py` |
| **SQLAlchemy + SQLite** | Queryable audit database replacing .md file logs | `app/services/audit_db.py` |

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

### Bug Fixes

**Split-order false positives (core bug)**
- The `AnomalyAgent` was matching against all-time seed CSV history, causing clean PRs (e.g., `pr_auto_approve`) to get false `POTENTIAL_SPLIT_ORDER` exceptions
- Fix: 30-day lookback window; CSV seed rows without timestamps are excluded from anomaly matching; only timestamped run history counts
- Result: `pr_auto_approve` now correctly produces `APPROVED` with no exceptions

**Web form `business_justification` NameError**
- Variable was defined inside a `st.form()` block but used outside it
- Fix: all form fields moved to top-level scope; form submit button replaced with plain `st.button()`

**PDF parsing robustness**
- Field extraction now uses regex with OCR-noise tolerance (flexible spacing around colons)
- Numeric fields (`quantity`, `unit_price`, `quotes_received`) strip non-numeric characters before parsing
- Graceful fallback line items when parsing fails

### Audit System Upgrade

Old system: `audit_log.md` (write-only, not queryable)

New system: `runs/audit.db` (SQLite via SQLAlchemy)
- `pipeline_runs` table — one record per run with decision, amounts, status
- `agent_steps` table — per-agent execution trace
- `exceptions` table — per-exception records with type, severity, rule reference
- REST endpoints: `GET /audit/runs`, `GET /audit/runs/{run_id}`, `GET /audit/stats`
- Live dashboard in Streamlit Audit tab

---

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
