"""
app.py — Streamlit Frontend for the Cloud9 MDT Extraction Pipeline.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Ensure project root is on sys.path so local modules import correctly
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from schema import COLUMNS, FIELD_GROUPS, KEY_TO_HEADER
from parse_docx import parse_docx
from extract_llm import extract_all_cases, CaseResult, FieldResult
from build_dataframe import build_dataframes
from write_excel import write_styled_workbook
from validate_agent import (
    validate_all,
    generate_validation_report,
    fix_all,
)

# ─── Paths ───────────────────────────────────────────────
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
PROTOTYPE_WORKBOOK = DATA_DIR / "hackathon-database-prototype.xlsx"
RAW_EXTRACTIONS = OUTPUT_DIR / "raw-extractions.json"

# ─── Derived lookups ─────────────────────────────────────
# Unique keys are safe for DataFrame columns; headers have duplicates.
KEY_LABELS: dict[str, str] = {}
for _col in COLUMNS:
    # Build a short readable label from the key
    KEY_LABELS[_col.key] = _col.key.replace("_", " ").title()

# ─── Page Config ─────────────────────────────────────────
st.set_page_config(
    page_title="Cloud9 MDT Extractor",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ──────────────────────────────────────────
st.markdown("""
<style>
    .issue-critical { background: #fff3f3; border-left: 4px solid #dc3545; padding: 8px 12px; margin: 4px 0; border-radius: 4px; }
    .issue-warning { background: #fff8e6; border-left: 4px solid #ffc107; padding: 8px 12px; margin: 4px 0; border-radius: 4px; }
    .issue-info { background: #f0f8ff; border-left: 4px solid #17a2b8; padding: 8px 12px; margin: 4px 0; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# Helper functions
# ════════════════════════════════════════════════════════

def _extractions_to_json(extractions: list[CaseResult]) -> list[dict]:
    """Convert CaseResult list to JSON-serialisable format."""
    raw = []
    for ext in extractions:
        case_data = {"case_index": ext.case_index, "fields": {}}
        for key, fr in ext.fields.items():
            case_data["fields"][key] = {
                "value": fr.value,
                "evidence": fr.evidence,
                "confidence": fr.confidence,
            }
        raw.append(case_data)
    return raw


def _json_to_extractions(raw_data: list[dict]) -> list[CaseResult]:
    """Rebuild CaseResult list from raw JSON."""
    results = []
    for case_data in raw_data:
        fields = {}
        for col in COLUMNS:
            fd = case_data.get("fields", {}).get(col.key, {})
            if isinstance(fd, dict):
                fields[col.key] = FieldResult(
                    key=col.key,
                    value=str(fd.get("value", "") or "").strip(),
                    evidence=str(fd.get("evidence", "") or "").strip(),
                    confidence=str(fd.get("confidence", "none") or "none").strip(),
                )
            else:
                fields[col.key] = FieldResult(
                    key=col.key, value="", evidence="", confidence="none",
                )
        results.append(CaseResult(
            case_index=case_data["case_index"],
            fields=fields,
            raw_llm_response="(loaded)",
            source_text="",
        ))
    return results


def _build_key_dfs(raw_data: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build DataFrames keyed by unique field keys (safe for display)."""
    data_rows, evidence_rows, confidence_rows = [], [], []
    for case_data in raw_data:
        d_row, e_row, c_row = {}, {}, {}
        for col in COLUMNS:
            fd = case_data.get("fields", {}).get(col.key, {})
            if isinstance(fd, dict):
                val = fd.get("value", "")
                d_row[col.key] = val if val else None
                e_row[col.key] = fd.get("evidence", "")
                c_row[col.key] = fd.get("confidence", "none") or "none"
            else:
                d_row[col.key] = None
                e_row[col.key] = ""
                c_row[col.key] = "none"
        data_rows.append(d_row)
        evidence_rows.append(e_row)
        confidence_rows.append(c_row)

    keys = [col.key for col in COLUMNS]
    return (
        pd.DataFrame(data_rows, columns=keys),
        pd.DataFrame(evidence_rows, columns=keys),
        pd.DataFrame(confidence_rows, columns=keys),
    )


def _build_excel_bytes(
    data_df: pd.DataFrame,
    evidence_df: pd.DataFrame,
    confidence_df: pd.DataFrame,
) -> bytes | None:
    """Write the styled workbook to a temp file and return bytes."""
    if not PROTOTYPE_WORKBOOK.exists():
        return None
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        write_styled_workbook(data_df, evidence_df, confidence_df, PROTOTYPE_WORKBOOK, tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ════════════════════════════════════════════════════════
# Sidebar
# ════════════════════════════════════════════════════════

st.sidebar.title("Cloud9 MDT Extractor")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    ["Run Pipeline", "Browse Results", "Validation Report"],
    index=0,
)

st.sidebar.markdown("---")

# LLM Provider selection
llm_provider = st.sidebar.selectbox(
    "LLM Provider",
    ["ollama", "gemini"],
    index=0,
    help="For hackathon: Use 'ollama' (local LLM). 'gemini' is for testing only.",
)
os.environ["LOCAL_LLM_PROVIDER"] = llm_provider

# Provider-specific configuration
if llm_provider == "ollama":
    st.sidebar.info("Using local Ollama LLM (hackathon compliant)")
    ollama_model = st.sidebar.selectbox(
        "Ollama Model",
        ["llama3.1:8b", "mistral:7b", "qwen3.5:9b"],
        index=0,
        help="Choose a model ≤5GB for hackathon compliance",
    )
    os.environ["LOCAL_LLM_MODEL"] = ollama_model

    ollama_url = st.sidebar.text_input(
        "Ollama Base URL",
        value=os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"),
        help="URL where Ollama is running",
    )
    os.environ["LOCAL_LLM_BASE_URL"] = ollama_url

elif llm_provider == "gemini":
    st.sidebar.warning("⚠️ Gemini is cloud-based. NOT allowed for hackathon submission!")
    # API key input
    api_key = st.sidebar.text_input(
        "Gemini API Key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Required for Gemini LLM (testing only)",
    )
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key

    gemini_model = st.sidebar.selectbox(
        "Gemini Model",
        ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
        index=0,
    )
    os.environ["GEMINI_MODEL"] = gemini_model

st.sidebar.markdown("---")
st.sidebar.caption("Cloud9 Clinical AI Hackathon")


# ════════════════════════════════════════════════════════
# PAGE 1: Run Pipeline
# ════════════════════════════════════════════════════════

if page == "Run Pipeline":
    st.title("Run Extraction Pipeline")
    st.markdown("Upload an MDT proforma DOCX file and run the full extraction pipeline.")

    # ── File upload ──
    uploaded_file = st.file_uploader(
        "Upload MDT Proforma (.docx)",
        type=["docx"],
        help="Upload the Word document containing MDT outcome proformas",
    )

    # ── Pipeline options ──
    col1, col2, col3 = st.columns(3)
    with col1:
        run_validation = st.checkbox("Run Validation Agent", value=True)
    with col2:
        run_fix = st.checkbox("Run Fix Agent", value=True)
    with col3:
        max_workers = st.slider("Parallel workers", 1, 20, 5, 1)

    col_a, col_b = st.columns(2)
    with col_a:
        case_filter = st.text_input(
            "Case filter (optional)",
            placeholder="e.g. 0-4 or 0,5,10",
            help="Leave blank to process all cases",
        )
    with col_b:
        max_cases = st.number_input("Max cases (0 = all)", min_value=0, value=0, step=1)

    # ── Run button ──
    if st.button("Run Pipeline", type="primary", use_container_width=True):
        # Validation checks based on provider
        if llm_provider == "gemini":
            if not os.getenv("GEMINI_API_KEY"):
                st.error("Please enter your Gemini API key in the sidebar.")
                st.stop()
        elif llm_provider == "ollama":
            # No API key needed for Ollama
            pass

        if not uploaded_file:
            st.error("Please upload a DOCX file first.")
            st.stop()

        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            docx_path = tmp.name

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        progress = st.progress(0, text="Starting pipeline...")
        status_area = st.empty()

        try:
            # ── Stage 1: Parse ──
            progress.progress(5, text="Stage 1: Parsing DOCX...")
            status_area.info("Parsing document structure...")
            all_cases = parse_docx(docx_path)
            st.toast(f"Parsed {len(all_cases)} cases from DOCX")

            # Apply filters
            cases = all_cases
            if case_filter:
                if "-" in case_filter:
                    start, end = map(int, case_filter.split("-"))
                    cases = [c for c in all_cases if start <= c.case_index <= end]
                else:
                    indices = set(map(int, case_filter.split(",")))
                    cases = [c for c in all_cases if c.case_index in indices]

            if max_cases > 0:
                cases = cases[:max_cases]

            st.session_state["cases"] = cases
            progress.progress(15, text=f"Stage 1 complete: {len(cases)} cases")

            # ── Stage 2: LLM Extraction ──
            progress.progress(20, text="Stage 2: Extracting with Gemini...")
            status_area.info(f"Extracting fields from {len(cases)} cases with {max_workers} workers...")
            t0 = time.time()
            extractions = extract_all_cases(cases, batch_delay=0.0, max_workers=max_workers)
            elapsed = time.time() - t0
            st.toast(f"Extraction complete in {elapsed:.1f}s")

            # Save raw extractions
            raw_data = _extractions_to_json(extractions)
            with open(RAW_EXTRACTIONS, "w") as f:
                json.dump(raw_data, f, indent=2)

            progress.progress(60, text="Stage 2 complete: extraction done")

            # ── Stage 3: Build DataFrames (header-based for Excel) ──
            progress.progress(65, text="Stage 3: Building DataFrames...")
            data_df, evidence_df, confidence_df = build_dataframes(extractions)
            progress.progress(70, text="Stage 3 complete")

            # ── Stage 4: Write Excel ──
            progress.progress(75, text="Stage 4: Writing Excel...")
            output_path = OUTPUT_DIR / "generated-database-cloud9.xlsx"
            if PROTOTYPE_WORKBOOK.exists():
                write_styled_workbook(
                    data_df, evidence_df, confidence_df,
                    PROTOTYPE_WORKBOOK, output_path,
                )

            progress.progress(80, text="Stage 4 complete: Excel written")

            # ── Stage 5: Validation ──
            if run_validation:
                progress.progress(82, text="Stage 5: Running validation agent...")
                status_area.info(f"Validating extractions against source with {max_workers} workers...")
                validations = validate_all(cases, extractions, batch_delay=0.0, max_workers=max_workers)
                report = generate_validation_report(
                    validations, str(OUTPUT_DIR / "validation-report.json")
                )
                st.session_state["validation_report"] = report
                st.toast(f"Validation: {report['total_issues']} issues found")
                progress.progress(90, text="Stage 5 complete: validation done")

                # ── Stage 6: Fix Agent ──
                if run_fix and report["total_issues"] > 0:
                    progress.progress(92, text="Stage 6: Running fix agent...")
                    status_area.info(f"Auto-correcting flagged fields with {max_workers} workers...")
                    extractions = fix_all(cases, extractions, validations, batch_delay=0.0, max_workers=max_workers)

                    raw_data = _extractions_to_json(extractions)
                    with open(RAW_EXTRACTIONS, "w") as f:
                        json.dump(raw_data, f, indent=2)

                    # Rebuild header-based DFs for Excel
                    data_df, evidence_df, confidence_df = build_dataframes(extractions)
                    if PROTOTYPE_WORKBOOK.exists():
                        write_styled_workbook(
                            data_df, evidence_df, confidence_df,
                            PROTOTYPE_WORKBOOK, output_path,
                        )
                    progress.progress(98, text="Stage 6 complete: fixes applied")

            # ── Store results in session ──
            st.session_state["extractions"] = raw_data
            # Store header-based DFs for Excel export
            st.session_state["excel_data_df"] = data_df
            st.session_state["excel_evidence_df"] = evidence_df
            st.session_state["excel_confidence_df"] = confidence_df

            progress.progress(100, text="Pipeline complete!")
            status_area.empty()

            # ── Summary metrics ──
            st.success("Pipeline finished successfully!")
            non_empty = data_df.notna().sum().sum()
            total_cells = data_df.shape[0] * data_df.shape[1]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Cases Processed", len(cases))
            m2.metric("Fields Extracted", int(non_empty))
            m3.metric("Total Cells", total_cells)
            m4.metric("Fill Rate", f"{100 * non_empty / total_cells:.1f}%")

            # ── Download buttons ──
            st.markdown("### Downloads")
            dl1, dl2 = st.columns(2)

            excel_bytes = _build_excel_bytes(data_df, evidence_df, confidence_df)
            if excel_bytes:
                dl1.download_button(
                    "Download Excel Workbook",
                    data=excel_bytes,
                    file_name="generated-database-cloud9.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

            dl2.download_button(
                "Download Raw JSON",
                data=json.dumps(raw_data, indent=2),
                file_name="raw-extractions.json",
                mime="application/json",
                use_container_width=True,
            )

        except Exception as e:
            progress.empty()
            status_area.empty()
            st.error(f"Pipeline failed: {e}")
            st.exception(e)
        finally:
            Path(docx_path).unlink(missing_ok=True)


# ════════════════════════════════════════════════════════
# PAGE 2: Browse Results
# ════════════════════════════════════════════════════════

elif page == "Browse Results":
    st.title("Browse Extraction Results")

    # Load data: prefer session state, fallback to raw-extractions.json
    raw_data = st.session_state.get("extractions")
    if raw_data is None and RAW_EXTRACTIONS.exists():
        with open(RAW_EXTRACTIONS) as f:
            raw_data = json.load(f)
        st.session_state["extractions"] = raw_data

    if raw_data is None:
        st.warning("No extraction results found. Run the pipeline first or ensure `output/raw-extractions.json` exists.")
        st.stop()

    # Build key-based DataFrames (unique column names, safe for st.dataframe)
    key_data_df, key_evidence_df, key_confidence_df = _build_key_dfs(raw_data)

    # ── Summary bar ──
    non_empty = key_data_df.notna().sum().sum()
    total_cells = key_data_df.shape[0] * key_data_df.shape[1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Cases", key_data_df.shape[0])
    m2.metric("Fields Per Case", key_data_df.shape[1])
    m3.metric("Populated Cells", int(non_empty))
    m4.metric("Fill Rate", f"{100 * non_empty / total_cells:.1f}%")

    st.markdown("---")

    # ── View mode toggle ──
    view_mode = st.radio(
        "View",
        ["Data Table", "Case Detail", "Field Group Explorer"],
        horizontal=True,
    )

    if view_mode == "Data Table":
        st.markdown("### Full Extraction Table")
        st.caption("Scroll horizontally to see all 88 columns")
        st.dataframe(key_data_df, use_container_width=True, height=500)

        # Download Excel (uses header-based DFs from build_dataframes)
        excel_data_df = st.session_state.get("excel_data_df")
        if excel_data_df is not None:
            excel_bytes = _build_excel_bytes(
                excel_data_df,
                st.session_state["excel_evidence_df"],
                st.session_state["excel_confidence_df"],
            )
        else:
            # Rebuild header-based DFs for Excel export
            extractions = _json_to_extractions(raw_data)
            hdr_data, hdr_ev, hdr_conf = build_dataframes(extractions)
            st.session_state["excel_data_df"] = hdr_data
            st.session_state["excel_evidence_df"] = hdr_ev
            st.session_state["excel_confidence_df"] = hdr_conf
            excel_bytes = _build_excel_bytes(hdr_data, hdr_ev, hdr_conf)

        if excel_bytes:
            st.download_button(
                "Download Excel",
                data=excel_bytes,
                file_name="generated-database-cloud9.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    elif view_mode == "Case Detail":
        case_idx = st.selectbox(
            "Select Case",
            range(len(raw_data)),
            format_func=lambda i: (
                f"Case {raw_data[i]['case_index']} — "
                + raw_data[i]["fields"].get("initials", {}).get("value", "?")
                + f" (NHS: {raw_data[i]['fields'].get('nhs_number', {}).get('value', 'N/A')})"
            ),
        )

        case = raw_data[case_idx]
        st.markdown(f"### Case {case['case_index']}")

        for group_name, group_cols in FIELD_GROUPS.items():
            with st.expander(
                group_name.replace("_", " ").title(),
                expanded=group_name in ("demographics", "endoscopy", "baseline_mri", "first_mdt"),
            ):
                for col in group_cols:
                    fd = case["fields"].get(col.key, {})
                    val = fd.get("value", "")
                    evidence = fd.get("evidence", "")
                    conf = fd.get("confidence", "none")

                    label = col.key.replace("_", " ")
                    if val:
                        conf_color = {"high": "green", "medium": "orange", "low": "red"}.get(conf, "gray")
                        st.markdown(
                            f"**{label}**: {val} "
                            f"&nbsp; :{conf_color}[{conf}]"
                        )
                        if evidence:
                            st.caption(f'Evidence: "{evidence}"')
                    else:
                        st.markdown(f"**{label}**: —")

    elif view_mode == "Field Group Explorer":
        group_name = st.selectbox(
            "Select Field Group",
            list(FIELD_GROUPS.keys()),
            format_func=lambda g: g.replace("_", " ").title(),
        )

        group_cols = FIELD_GROUPS[group_name]
        group_keys = [col.key for col in group_cols]

        st.markdown(f"### {group_name.replace('_', ' ').title()}")
        st.dataframe(key_data_df[group_keys], use_container_width=True, height=400)

        # Confidence distribution
        st.markdown("#### Confidence Distribution")
        conf_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
        for key in group_keys:
            for val in key_confidence_df[key]:
                v = str(val).strip().lower()
                if v in conf_counts:
                    conf_counts[v] += 1

        conf_df = pd.DataFrame(
            {"Confidence": list(conf_counts.keys()), "Count": list(conf_counts.values())}
        )
        st.bar_chart(conf_df, x="Confidence", y="Count")


# ════════════════════════════════════════════════════════
# PAGE 3: Validation Report
# ════════════════════════════════════════════════════════

elif page == "Validation Report":
    st.title("Validation Report")

    # Load report: session state or file
    report = st.session_state.get("validation_report")
    if report is None:
        report_path = OUTPUT_DIR / "validation-report.json"
        if report_path.exists():
            with open(report_path) as f:
                report = json.load(f)
            st.session_state["validation_report"] = report

    if report is None:
        st.warning("No validation report found. Run the pipeline with validation enabled.")
        st.stop()

    # ── Summary metrics ──
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Cases", report["total_cases"])
    m2.metric("Passed", report["passed"])
    m3.metric("Need Review", report["review_needed"])
    m4.metric("Failed", report["failed"])

    c1, c2 = st.columns(2)
    c1.metric("Total Issues", report["total_issues"])
    c2.metric("Critical Issues", report["critical_issues"])

    st.markdown("---")

    # ── Status distribution chart ──
    st.markdown("### Case Status Distribution")
    status_counts = pd.DataFrame({
        "Status": ["Passed", "Review Needed", "Failed"],
        "Count": [report["passed"], report["review_needed"], report["failed"]],
    })
    st.bar_chart(status_counts, x="Status", y="Count")

    st.markdown("---")

    # ── Per-case details ──
    st.markdown("### Case Details")

    status_filter = st.multiselect(
        "Filter by status",
        ["pass", "review_needed", "fail"],
        default=["pass", "review_needed", "fail"],
        format_func=lambda s: {"pass": "Passed", "review_needed": "Review Needed", "fail": "Failed"}.get(s, s),
    )

    matched = 0
    for case_report in report.get("cases", []):
        if case_report["status"] not in status_filter:
            continue
        matched += 1

        status_icon = {"pass": "OK", "review_needed": "REVIEW", "fail": "FAIL"}.get(
            case_report["status"], "?"
        )

        with st.expander(
            f"[{status_icon}] Case {case_report['case_index']} — "
            f"{case_report['fields_checked']} checked, "
            f"{case_report['fields_flagged']} flagged",
            expanded=case_report["status"] == "fail",
        ):
            c1, c2, c3 = st.columns(3)
            c1.metric("Fields Checked", case_report["fields_checked"])
            c2.metric("Fields OK", case_report["fields_ok"])
            c3.metric("Fields Flagged", case_report["fields_flagged"])

            if not case_report.get("issues"):
                st.success("All fields passed validation.")
            else:
                for issue in case_report["issues"]:
                    css_class = f"issue-{issue['severity']}"
                    severity_label = issue["severity"].upper()

                    st.markdown(
                        f'<div class="{css_class}">'
                        f'<strong>{severity_label}</strong> — '
                        f'<code>{issue["field"]}</code> ({issue["type"]})<br/>'
                        f'{issue["description"]}'
                        + (f'<br/><em>Suggested: {issue["suggested_value"]}</em>' if issue.get("suggested_value") else "")
                        + "</div>",
                        unsafe_allow_html=True,
                    )

    if matched == 0:
        st.info("No cases match the selected filters.")

    # ── Download report ──
    st.markdown("---")
    st.download_button(
        "Download Validation Report (JSON)",
        data=json.dumps(report, indent=2),
        file_name="validation-report.json",
        mime="application/json",
    )
