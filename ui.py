

import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from app.schemas.purchase_requisition import PurchaseRequisition
from app.services.pdf_parser import parse_requisition_pdf, extract_text_from_pdf
from app.services.data_loader import load_catalog_items, load_approved_vendors
from app.pipeline import run_pipeline
from app.services.audit_db import (
    get_recent_runs,
    get_audit_stats,
    get_exception_summary,
    get_exceptions_for_run,
    get_run_by_id,
    get_pr_data_for_rerun,
)
from app.services.auth import authenticate, get_all_users, create_user, update_user_role, deactivate_user, update_user_password
from app.services.runs_manager import get_runs_disk_usage, cleanup_old_runs
from app.services.export_service import runs_to_csv, exceptions_to_csv, audit_stats_to_csv


st.set_page_config(
    page_title="IPRMS",
    page_icon="📄",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent



# Session state helpers


def _is_logged_in() -> bool:
    return st.session_state.get("auth_user") is not None


def _current_user() -> dict | None:
    return st.session_state.get("auth_user")


def _is_admin() -> bool:
    user = _current_user()
    return user is not None and user.get("role") == "admin"


def _logout():
    st.session_state.pop("auth_user", None)
    st.rerun()


# Login page


def render_login():
    col_l, col_c, col_r = st.columns([2, 3, 2])
    with col_c:
        st.markdown("## 📄 IPRMS Login")
        st.caption("Intelligent Purchase Requisition Management System")
        st.divider()

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="e.g. admin or user")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if not username.strip() or not password.strip():
                st.error("Please enter both username and password.")
            else:
                user = authenticate(username.strip(), password.strip())
                if user:
                    st.session_state["auth_user"] = user
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

        st.info("Default accounts: **admin** / admin123 · **user** / user123")



# Shared result display


def _decision_badge(decision: str) -> str:
    if decision == "APPROVED":
        return "✅ APPROVED"
    elif decision == "REVIEW_REQUIRED":
        return "🔶 REVIEW REQUIRED"
    return f"❓ {decision}"


def display_results(result: dict):
    final_result = result.get("final_result", {})
    approval_packet = final_result.get("approval_packet", {})
    vendor_risk = result.get("vendor_risk", {})
    classification_detail = result.get("classification_detail", {})
    pipeline_errors = result.get("pipeline_errors", [])

    if pipeline_errors:
        st.error(f"Pipeline errors: {pipeline_errors}")

    st.success("Pipeline completed ✓")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Final Decision", _decision_badge(final_result.get("final_decision", "?")))
    col2.metric("Required Approver", approval_packet.get("required_approver", "—"))
    col3.metric("Exceptions", len(result.get("compliance", {}).get("exceptions", [])))
    col4.metric(
        "Vendor Risk Score",
        f"{vendor_risk.get('risk_score', '—')}/10" if vendor_risk.get("risk_score") else "—",
    )

    st.subheader("Decision Reason")
    st.write(approval_packet.get("reason", "—"))

    st.subheader("AI Narrative Summary")
    st.write(approval_packet.get("narrative_summary", "—"))

    if classification_detail:
        with st.expander("🤖 LLM Classification Detail", expanded=False):
            st.json(classification_detail)

    if vendor_risk:
        with st.expander("🏪 Vendor Risk Assessment", expanded=False):
            method = vendor_risk.get("assessment_method", "")
            if "llm" in method:
                st.success(f"LLM-powered assessment ({method})")
            else:
                st.info(f"Rule-based assessment ({method})")
            st.write(f"**Risk Score:** {vendor_risk.get('risk_score', '—')}/10")
            st.write(f"**Narrative:** {vendor_risk.get('risk_narrative', '—')}")
            st.write(f"**Due Diligence Required:** {vendor_risk.get('due_diligence_required', '—')}")
            st.write(f"**Recommended Action:** {vendor_risk.get('recommended_action', '—')}")

    tab_a, tab_b, tab_c, tab_d, tab_e = st.tabs([
        "Budget", "Vendor Match", "Anomaly", "Compliance", "PO Draft"
    ])

    with tab_a:
        st.json(result.get("budget_check", {}))

    with tab_b:
        st.json(result.get("vendor_match", {}))

    with tab_c:
        anomaly = result.get("anomaly_check", {})
        if anomaly.get("anomaly_detected"):
            st.error(f"⚠️ Split-order pattern detected! Related PRs: {anomaly.get('related_prs')}")
        else:
            st.success("No split-order anomaly detected")
        st.json(anomaly)

    with tab_d:
        compliance = result.get("compliance", {})
        exceptions = compliance.get("exceptions", [])
        if exceptions:
            for exc in exceptions:
                severity = exc.get("severity", "LOW")
                color = "🔴" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
                st.write(f"{color} **{exc['type']}** ({severity}) — {exc['message']}")
        else:
            st.success("No compliance exceptions")
        with st.expander("Full compliance JSON"):
            st.json(compliance)

    with tab_e:
        po_draft = final_result.get("po_draft")
        if po_draft is None:
            st.warning("PO draft not generated — review required first.")
        else:
            st.json(po_draft)

    run_dir = result.get("run_artifacts", {}).get("run_directory", "—")
    st.caption(f"Run artifacts saved to: `{run_dir}`")


# Main app 


def render_app():
    user = _current_user()

    
    col_title, col_user, col_logout = st.columns([7, 2, 1])
    with col_title:
        role_badge = "🔑 Admin" if _is_admin() else "👤 User"
        st.title(f"📄 IPRMS  {role_badge}")
        st.caption("Multi-agent procurement pipeline · LangGraph · LangChain · SQLite Audit")
    with col_user:
        st.markdown(f"**{user['display_name']}**  \n`{user['username']}`")
    with col_logout:
        if st.button("Logout"):
            _logout()

    
    try:
        disk = get_runs_disk_usage()
        if disk["at_limit"]:
            st.warning(
                f"⚠️ Run storage near limit: {disk['run_count']} / {disk['max_runs']} runs "
                f"({disk['total_mb']} MB). Oldest runs will be auto-deleted."
            )
    except Exception:
        pass

   
    admin_tabs = ["📋 Scenario Demo", "📝 Web Form", "📄 PDF Upload",
                  "🔍 Audit Dashboard", "⚙️ Admin Panel"]
    user_tabs  = ["📋 Scenario Demo", "📝 Web Form", "📄 PDF Upload",
                  "🔍 Audit Dashboard"]

    tab_labels = admin_tabs if _is_admin() else user_tabs
    tabs = st.tabs(tab_labels)

    tab1 = tabs[0]
    tab2 = tabs[1]
    tab3 = tabs[2]
    tab4 = tabs[3]
    tab_admin = tabs[4] if _is_admin() else None

    
    with tab1:
        st.header("Scenario Demo")
        st.info(
            "Select a pre-built PR bundle scenario. "
            "All scenarios run through the LangGraph pipeline."
        )

        scenario_dir = BASE_DIR / "data" / "pr_bundles"
        scenario_files = sorted([f for f in scenario_dir.glob("*.json")])

        selected_file = st.selectbox(
            "Select a PR scenario",
            scenario_files,
            format_func=lambda p: p.name,
        )

        if selected_file:
            with open(selected_file, "r", encoding="utf-8") as f:
                pr_data = json.load(f)

            with st.expander("Input Purchase Requisition JSON", expanded=False):
                st.json(pr_data)

            if st.button("▶ Run Scenario Pipeline"):
                with st.spinner("Running LangGraph pipeline..."):
                    pr = PurchaseRequisition(**pr_data)
                    result = run_pipeline(pr, input_source="SCENARIO")
                display_results(result)

    
    with tab2:
        st.header("Web Form Entry")

        catalog_items = load_catalog_items()
        approved_vendors = load_approved_vendors()

        catalog_options = {
            f"{item.description} ({item.item_id})": item
            for item in catalog_items
        }
        all_vendor_names = [v.vendor_name for v in approved_vendors]

        st.subheader("Catalogue Selection")

        selected_catalog_label = st.selectbox(
            "Select Equipment / Catalogue Item",
            list(catalog_options.keys()),
            key="catalog_sel",
        )
        selected_catalog_item = catalog_options[selected_catalog_label]

        vendor_choice = st.radio(
            "Vendor Selection",
            ["Use recommended vendor", "Choose vendor manually"],
            key="vendor_radio",
        )

        if vendor_choice == "Use recommended vendor":
            vendor_name = selected_catalog_item.approved_vendor
            st.info(f"Recommended Vendor: {vendor_name}")
        else:
            vendor_name = st.selectbox("Select Vendor", all_vendor_names, key="vendor_manual")

        st.write(f"**Item ID:** {selected_catalog_item.item_id}")
        st.write(f"**Description:** {selected_catalog_item.description}")
        st.write(f"**Unit Price:** {selected_catalog_item.unit_price} {selected_catalog_item.currency}")

        st.subheader("Requisition Details")

        pr_id = st.text_input("PR ID", "PR-WEB-001", key="wf_pr_id")
        requestor_name = st.text_input("Requestor Name", "Jane Miller", key="wf_req")

        department = st.selectbox(
            "Department",
            ["IT", "HR", "Finance", "Operations", "Engineering"],
            key="wf_dept",
        )

        cost_center = st.selectbox(
            "Cost Center",
            ["IT001", "HR001", "FIN001", "OPS001", "ENG001"],
            key="wf_cc",
        )

        gl_account_label = st.selectbox(
            "GL Account",
            ["6100 - IT Hardware", "6200 - Software Licenses", "6300 - Office Supplies"],
            key="wf_gl",
        )
        selected_gl_account = gl_account_label.split(" - ")[0]

        spend_type = st.selectbox("Spend Type", ["OPEX", "CAPEX"], key="wf_spend")

        procurement_type = st.selectbox(
            "Procurement Type",
            ["STANDARD", "EMERGENCY", "FRAMEWORK_AGREEMENT", "BLANKET_ORDER", "SOLE_SOURCE"],
            key="wf_proc_type",
        )

        quantity = st.number_input("Quantity", min_value=1, value=1, key="wf_qty")

        business_justification = st.text_area(
            "Business Justification",
            "Standard equipment purchase for departmental needs.",
            key="wf_justification",
        )

        quotes_received = st.number_input(
            "Quotes Received", min_value=0, value=0, key="wf_quotes"
        )

        sole_source = st.checkbox("Sole Source Requested", key="wf_sole")
        sole_source_justification = ""
        if sole_source:
            sole_source_justification = st.text_area(
                "Sole Source Justification", key="wf_sole_just"
            )

        if st.button("▶ Run Web Form Pipeline", key="wf_run"):
            
            errors = []
            if not pr_id.strip():
                errors.append("PR ID cannot be empty.")
            if not requestor_name.strip():
                errors.append("Requestor Name cannot be empty.")
            if quantity < 1:
                errors.append("Quantity must be at least 1.")
            if not business_justification.strip():
                errors.append("Business Justification cannot be empty.")
            if sole_source and not sole_source_justification.strip():
                errors.append("Sole Source Justification is required when Sole Source is checked.")

            if errors:
                for e in errors:
                    st.error(f"⚠️ {e}")
            else:
                pr = PurchaseRequisition(
                    pr_id=pr_id.strip(),
                    requestor_name=requestor_name.strip(),
                    department=department,
                    cost_center=cost_center,
                    business_justification=business_justification.strip(),
                    vendor_name=vendor_name,
                    gl_account=selected_gl_account,
                    spend_type=spend_type,
                    procurement_type=procurement_type,
                    quotes_received=quotes_received,
                    sole_source_requested=sole_source,
                    sole_source_justification=sole_source_justification if sole_source else None,
                    line_items=[
                        {
                            "item_id": selected_catalog_item.item_id,
                            "description": selected_catalog_item.description,
                            "quantity": quantity,
                            "unit_price": selected_catalog_item.unit_price,
                            "currency": selected_catalog_item.currency,
                        }
                    ],
                )

                with st.expander("Generated Purchase Requisition", expanded=False):
                    st.json(pr.model_dump())

                with st.spinner("Running LangGraph pipeline..."):
                    result = run_pipeline(pr, input_source="WEB_FORM")
                display_results(result)

    
    with tab3:
        st.header("PDF Upload")

        pdf_mode = st.radio(
            "Extraction Mode",
            ["🔍 Smart (rule-based, fast)", "🤖 LLM-powered (any layout, slower)"],
            key="pdf_mode",
        )
        use_llm = "LLM" in pdf_mode

        st.info(
            "Upload a PDF purchase requisition. "
            "**Smart mode** uses rule-based field extraction for structured PDFs. "
            "**LLM mode** uses Claude to handle any layout, including free-form documents. "
            "Both modes apply OCR correction on scanned PDFs."
        )

        uploaded_file = st.file_uploader(
            "Upload PDF requisition (digital or scanned)",
            type=["pdf"],
            key="pdf_upload",
        )

        if uploaded_file is not None:
            st.success(f"Uploaded: {uploaded_file.name} ({uploaded_file.size:,} bytes)")

            col_prev, col_run = st.columns(2)

            with col_prev:
                if st.button("🔍 Preview Extracted Text"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name
                    uploaded_file.seek(0)

                    text, method = extract_text_from_pdf(tmp_path)
                    import os; os.unlink(tmp_path)

                    st.info(f"Extraction method: **{method}**")
                    st.text_area("Extracted Text (preview)", text[:2000], height=200)

            with col_run:
                if st.button("▶ Run PDF Pipeline"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name

                    try:
                        if use_llm:
                            from app.services.pdf_parser import parse_requisition_pdf_flexible
                            with st.spinner("LLM extracting PR from PDF..."):
                                pr, meta = parse_requisition_pdf_flexible(tmp_path)
                            llm_used = meta.get("llm_used", False)
                            corrections = meta.get("ocr_corrections", [])
                            if llm_used:
                                st.success("✅ LLM extraction successful")
                            else:
                                st.warning(f"⚠️ LLM fallback: {meta.get('llm_error', 'unknown')} — used rule-based parser")
                        else:
                            with st.spinner("Parsing PDF..."):
                                pr = parse_requisition_pdf(tmp_path)
                            corrections = getattr(pr, "__dict__", {}).get("_ocr_corrections", [])

                        
                        if corrections:
                            with st.expander(f"🔧 OCR Auto-Corrections Applied ({len(corrections)})", expanded=True):
                                for c in corrections:
                                    st.write(f"• {c}")

                        with st.expander("Extracted Purchase Requisition", expanded=False):
                            st.json(pr.model_dump())

                        with st.spinner("Running pipeline..."):
                            result = run_pipeline(pr, input_source="PDF")

                        display_results(result)

                    except Exception as e:
                        st.error(f"PDF processing error: {e}")
                    finally:
                        import os; os.unlink(tmp_path)

    
    with tab4:
        st.header("🔍 Audit Dashboard")
        st.caption("Live audit data from SQLite database.")

        col_refresh, col_export_runs, col_export_stats = st.columns([2, 2, 2])
        with col_refresh:
            if st.button("🔄 Refresh"):
                st.rerun()
        with col_export_runs:
            try:
                runs_data = get_recent_runs(limit=200)
                csv_bytes = runs_to_csv(runs_data)
                st.download_button(
                    "⬇ Export Runs CSV",
                    data=csv_bytes,
                    file_name=f"iprms_runs_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )
            except Exception:
                pass
        with col_export_stats:
            try:
                stats = get_audit_stats()
                exc_sum = get_exception_summary()
                stats_csv = audit_stats_to_csv(stats, exc_sum)
                st.download_button(
                    "⬇ Export Stats CSV",
                    data=stats_csv,
                    file_name=f"iprms_stats_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )
            except Exception:
                pass

        try:
            stats = get_audit_stats()
            exc_summary = get_exception_summary()
            recent_runs = get_recent_runs(limit=50)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total Runs", stats["total_runs"])
            c2.metric("Approved", stats["approved"])
            c3.metric("Review Required", stats["review_required"])
            c4.metric("Anomalies", stats["anomalies_detected"])
            c5.metric("Avg Exceptions", stats["avg_exceptions_per_run"])

            st.divider()

            col_runs, col_exc = st.columns([6, 4])

            with col_runs:
                st.subheader("Recent Pipeline Runs")
                if recent_runs:
                    df = pd.DataFrame([
                        {
                            "PR ID": r["pr_id"],
                            "Decision": r["final_decision"],
                            "Approver": r["required_approver"],
                            "Exceptions": r["exception_count"],
                            "Anomaly": "⚠️" if r["anomaly_detected"] else "—",
                            "Source": r["input_source"],
                            "Budget": r["budget_status"],
                            "Vendor": r["vendor_name"],
                            "Amount": r["total_amount"],
                        }
                        for r in recent_runs
                    ])
                    st.dataframe(df, use_container_width=True, hide_index=True)

                    
                    st.download_button(
                        "⬇ Export Runs Table CSV",
                        data=runs_to_csv(recent_runs),
                        file_name="iprms_runs_table.csv",
                        mime="text/csv",
                        key="dl_runs_table",
                    )
                else:
                    st.info("No runs yet.")

            with col_exc:
                st.subheader("Exception Frequency")
                if exc_summary:
                    df_exc = pd.DataFrame(exc_summary)
                    st.dataframe(df_exc, use_container_width=True, hide_index=True)
                else:
                    st.info("No exceptions recorded yet.")

            st.divider()
            st.subheader("Run Detail Inspector")

            if recent_runs:
                run_options = [r["run_id"] for r in recent_runs]
                selected_run_id = st.selectbox("Select a run to inspect", run_options)

                if selected_run_id:
                    run_detail = next((r for r in recent_runs if r["run_id"] == selected_run_id), None)
                    if run_detail:
                        c_detail, c_actions = st.columns([5, 2])
                        with c_detail:
                            st.json(run_detail)

                        with c_actions:
                            st.markdown("**Actions**")

                            
                            if st.button("🔁 Re-run this PR", key=f"rerun_{selected_run_id}"):
                                pr_data = get_pr_data_for_rerun(selected_run_id)
                                if pr_data:
                                    try:
                                        pr = PurchaseRequisition(**pr_data)
                                        with st.spinner("Re-running pipeline..."):
                                            result = run_pipeline(pr, input_source="RERUN")
                                        st.success("Re-run complete!")
                                        display_results(result)
                                    except Exception as e:
                                        st.error(f"Re-run failed: {e}")
                                else:
                                    st.warning("PR data not available for this run.")

                            
                            exc_detail = get_exceptions_for_run(selected_run_id)
                            if exc_detail:
                                st.download_button(
                                    "⬇ Exceptions CSV",
                                    data=exceptions_to_csv(exc_detail),
                                    file_name=f"exceptions_{selected_run_id}.csv",
                                    mime="text/csv",
                                    key=f"dl_exc_{selected_run_id}",
                                )

                        exc_detail = get_exceptions_for_run(selected_run_id)
                        if exc_detail:
                            st.write(f"**Exceptions ({len(exc_detail)}):**")
                            for exc in exc_detail:
                                severity = exc.get("severity", "LOW")
                                icon = "🔴" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
                                st.write(f"{icon} `{exc['exception_type']}` — {exc['message']}")

        except Exception as e:
            st.error(f"Audit database error: {e}")
            st.info("Run a scenario first to initialize the audit database.")

    
    if tab_admin is not None:
        with tab_admin:
            st.header("⚙️ Admin Panel")

            admin_tab_a, admin_tab_b, admin_tab_c, admin_tab_d, admin_tab_e = st.tabs([
                "👥 User Management",
                "🏭 Vendors",
                "💰 Budget",
                "📦 Catalogue",
                "🗑 Run Storage",
            ])

            
            with admin_tab_a:
                st.subheader("User Management")
                users = get_all_users()
                df_users = pd.DataFrame([
                    {
                        "ID": u["id"],
                        "Username": u["username"],
                        "Display Name": u["display_name"],
                        "Role": u["role"],
                        "Active": "✅" if u["is_active"] else "❌",
                        "Last Login": u["last_login"] or "Never",
                    }
                    for u in users
                ])
                st.dataframe(df_users, use_container_width=True, hide_index=True)

                st.divider()
                col_new, col_edit = st.columns(2)

                with col_new:
                    st.subheader("Create New User")
                    with st.form("new_user_form"):
                        new_username = st.text_input("Username")
                        new_display = st.text_input("Display Name")
                        new_password = st.text_input("Password", type="password")
                        new_role = st.selectbox("Role", ["user", "admin"])
                        if st.form_submit_button("Create User"):
                            if not new_username.strip() or not new_password.strip():
                                st.error("Username and password are required.")
                            else:
                                try:
                                    create_user(new_username.strip(), new_display.strip() or new_username, new_password, new_role)
                                    st.success(f"User '{new_username}' created.")
                                    st.rerun()
                                except ValueError as e:
                                    st.error(str(e))

                with col_edit:
                    st.subheader("Edit Existing User")
                    user_ids = [(u["id"], u["username"]) for u in users]
                    edit_user_label = st.selectbox(
                        "Select User",
                        [f"{uid} — {uname}" for uid, uname in user_ids],
                        key="edit_user_sel",
                    )
                    edit_uid = int(edit_user_label.split(" — ")[0])

                    with st.form("edit_user_form"):
                        new_role_edit = st.selectbox("Change Role To", ["user", "admin"], key="edit_role")
                        new_pw = st.text_input("New Password (leave blank to keep)", type="password", key="edit_pw")
                        deactivate = st.checkbox("Deactivate this user", key="edit_deactivate")
                        if st.form_submit_button("Apply Changes"):
                            if new_role_edit:
                                update_user_role(edit_uid, new_role_edit)
                            if new_pw.strip():
                                update_user_password(edit_uid, new_pw.strip())
                            if deactivate:
                                deactivate_user(edit_uid)
                            st.success("User updated.")
                            st.rerun()

            
            with admin_tab_b:
                st.subheader("Edit Approved Vendors")
                vendor_path = BASE_DIR / "data" / "sample_data" / "approved_vendors.csv"

                vendors_df = pd.read_csv(vendor_path)
                edited_vendors = st.data_editor(
                    vendors_df,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="vendors_editor",
                )

                col_save, col_dl = st.columns(2)
                with col_save:
                    if st.button("💾 Save Vendor Changes"):
                        edited_vendors.to_csv(vendor_path, index=False)
                        st.success("Vendors saved.")
                with col_dl:
                    st.download_button(
                        "⬇ Download Vendors CSV",
                        data=edited_vendors.to_csv(index=False).encode(),
                        file_name="approved_vendors.csv",
                        mime="text/csv",
                    )

            
            with admin_tab_c:
                st.subheader("Edit Budget Snapshot")
                budget_path = BASE_DIR / "data" / "sample_data" / "budget_snapshot.csv"

                budget_df = pd.read_csv(budget_path)
                edited_budget = st.data_editor(
                    budget_df,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="budget_editor",
                )

                col_save_b, col_dl_b = st.columns(2)
                with col_save_b:
                    if st.button("💾 Save Budget Changes"):
                        edited_budget.to_csv(budget_path, index=False)
                        st.success("Budget saved.")
                with col_dl_b:
                    st.download_button(
                        "⬇ Download Budget CSV",
                        data=edited_budget.to_csv(index=False).encode(),
                        file_name="budget_snapshot.csv",
                        mime="text/csv",
                    )

            
            with admin_tab_d:
                st.subheader("Edit Catalogue Pricing")
                catalog_path = BASE_DIR / "data" / "sample_data" / "catalogue_pricing.csv"

                catalog_df = pd.read_csv(catalog_path)
                edited_catalog = st.data_editor(
                    catalog_df,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="catalog_editor",
                )

                col_save_c, col_dl_c = st.columns(2)
                with col_save_c:
                    if st.button("💾 Save Catalogue Changes"):
                        edited_catalog.to_csv(catalog_path, index=False)
                        st.success("Catalogue saved.")
                with col_dl_c:
                    st.download_button(
                        "⬇ Download Catalogue CSV",
                        data=edited_catalog.to_csv(index=False).encode(),
                        file_name="catalogue_pricing.csv",
                        mime="text/csv",
                    )

            
            with admin_tab_e:
                st.subheader("Run Storage Management")
                try:
                    disk = get_runs_disk_usage()
                    col_d1, col_d2, col_d3 = st.columns(3)
                    col_d1.metric("Run Folders", disk["run_count"])
                    col_d2.metric("Disk Usage", f"{disk['total_mb']} MB")
                    col_d3.metric("Max Runs", disk["max_runs"])

                    if disk["at_limit"]:
                        st.warning("Storage is at limit. Auto-cleanup will run on next pipeline execution.")
                except Exception as e:
                    st.error(f"Could not read disk info: {e}")

                st.divider()
                col_clean, col_clear = st.columns(2)
                with col_clean:
                    if st.button("🧹 Cleanup Old Runs (keep last 50)"):
                        result = cleanup_old_runs()
                        if result["deleted_count"] > 0:
                            st.success(f"Deleted {result['deleted_count']} old run(s). {result['remaining']} remain.")
                        else:
                            st.info("Nothing to clean up — under 50 runs.")

                with col_clear:
                    if st.button("🗑 Clear ALL Run History", type="primary"):
                        runs_dir = BASE_DIR / "runs"
                        if runs_dir.exists():
                            for item in runs_dir.iterdir():
                                if item.is_dir():
                                    shutil.rmtree(item)
                        st.success("All run history cleared (database files preserved).")
                        st.rerun()

                st.info(
                    "**Note:** Run folders are auto-cleaned after every pipeline execution. "
                    "Only the last 50 runs are kept on disk. The SQLite audit database "
                    "is not affected by folder cleanup."
                )

                # API key info
                st.divider()
                st.subheader("API Access")
                import os
                api_key = os.environ.get("IPRMS_API_KEY", "iprms-dev-key")
                st.code(f"X-API-Key: {api_key}", language="text")
                st.caption("Pass this header with all API requests to port 8000.")





if _is_logged_in():
    render_app()
else:
    render_login()
