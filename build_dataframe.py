"""
build_dataframe.py — Convert LLM extraction results into pandas DataFrames.

Produces three parallel DataFrames (50 rows × 88 columns each):
  data_df       — extracted values (for the main Excel sheet)
  evidence_df   — verbatim evidence quotes (for comments + Evidence Map)
  confidence_df — confidence levels per cell
"""

from __future__ import annotations

import pandas as pd

from extract_llm import CaseResult, FieldResult
from schema import COLUMNS, KEY_TO_HEADER, HEADERS


def build_dataframes(
    results: list[CaseResult],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Build the main data, evidence, and confidence DataFrames from extraction results.
    """
    # Pre-processing: infer endoscopy_type from evidence/findings when LLM left type blank
    for result in results:
        endo_type_fr = result.fields.get("endoscopy_type")
        endo_findings_fr = result.fields.get("endoscopy_findings")
        if endo_type_fr and not endo_type_fr.value:
            # Check if we have evidence or findings that indicate the type
            combined = (endo_type_fr.evidence or "") + " " + (
                endo_findings_fr.evidence if endo_findings_fr else ""
            )
            combined_lower = combined.strip().lower()
            if "flexi" in combined_lower or "sigmoidoscopy" in combined_lower:
                endo_type_fr.value = "flexi sig"
                endo_type_fr.confidence = "medium"
            elif "colonoscop" in combined_lower:
                if "incomplete" in combined_lower:
                    endo_type_fr.value = "incomplete colonoscopy"
                else:
                    endo_type_fr.value = "Colonoscopy complete"
                endo_type_fr.confidence = "medium"

    data_rows = []
    evidence_rows = []
    confidence_rows = []

    for result in results:
        data_row = {}
        evidence_row = {}
        confidence_row = {}

        for col in COLUMNS:
            header = col.header
            fr: FieldResult | None = result.fields.get(col.key)

            if fr and fr.value:
                data_row[header] = fr.value
                evidence_row[header] = fr.evidence
                confidence_row[header] = fr.confidence
            else:
                data_row[header] = None
                evidence_row[header] = ""
                confidence_row[header] = "none"

        data_rows.append(data_row)
        evidence_rows.append(evidence_row)
        confidence_rows.append(confidence_row)

    data_df = pd.DataFrame(data_rows, columns=HEADERS)
    evidence_df = pd.DataFrame(evidence_rows, columns=HEADERS)
    confidence_df = pd.DataFrame(confidence_rows, columns=HEADERS)

    # Post-processing: convert MRN and NHS number to integers
    for int_col_key in ("mrn", "nhs_number"):
        header = KEY_TO_HEADER[int_col_key]
        data_df[header] = pd.to_numeric(data_df[header], errors="coerce")

    # Post-processing: convert DOB to datetime
    dob_header = KEY_TO_HEADER["dob"]
    data_df[dob_header] = pd.to_datetime(
        data_df[dob_header], format="%d/%m/%Y", errors="coerce"
    )

    # Post-processing: normalize endoscopy_type values
    endo_header = KEY_TO_HEADER["endoscopy_type"]
    endo_map = {
        "colonoscopy": "Colonoscopy complete",
        "colonoscopy complete": "Colonoscopy complete",
        "complete colonoscopy": "Colonoscopy complete",
        "incomplete colonoscopy": "incomplete colonoscopy",
        "flexi sig": "flexi sig",
        "flexible sigmoidoscopy": "flexi sig",
    }
    data_df[endo_header] = data_df[endo_header].apply(
        lambda v: endo_map.get(str(v).strip().lower(), v) if pd.notna(v) else v
    )

    # Post-processing: normalize CRM values ("unsafe" -> "threatened")
    for crm_key in ("baseline_mri_mrCRM", "second_mri_mrCRM", "mri_12wk_mrCRM"):
        header = KEY_TO_HEADER.get(crm_key)
        if header and header in data_df.columns:
            data_df[header] = data_df[header].apply(
                lambda v: "threatened" if pd.notna(v) and str(v).strip().lower() == "unsafe" else v
            )

    # Sort by NHS number for consistent ordering
    nhs_header = KEY_TO_HEADER["nhs_number"]
    sort_order = data_df[nhs_header].sort_values(na_position="last", kind="stable").index
    data_df = data_df.loc[sort_order].reset_index(drop=True)
    evidence_df = evidence_df.loc[sort_order].reset_index(drop=True)
    confidence_df = confidence_df.loc[sort_order].reset_index(drop=True)

    return data_df, evidence_df, confidence_df
