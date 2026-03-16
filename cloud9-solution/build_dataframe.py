"""
build_dataframe.py — Convert LLM extraction results into pandas DataFrames.

Produces three parallel DataFrames (50 rows × 88 columns each):
  data_df       — extracted values (for the main Excel sheet)
  evidence_df   — verbatim evidence quotes (for comments + Evidence Map)
  confidence_df — confidence levels per cell
"""

import pandas as pd

from extract_llm import CaseResult, FieldResult
from schema import COLUMNS, KEY_TO_HEADER, HEADERS


def build_dataframes(
    results: list[CaseResult],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Build the main data, evidence, and confidence DataFrames from extraction results.
    """
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

    # Sort by NHS number for consistent ordering
    nhs_header = KEY_TO_HEADER["nhs_number"]
    sort_index = data_df[nhs_header].argsort(kind="stable")
    data_df = data_df.iloc[sort_index].reset_index(drop=True)
    evidence_df = evidence_df.iloc[sort_index].reset_index(drop=True)
    confidence_df = confidence_df.iloc[sort_index].reset_index(drop=True)

    return data_df, evidence_df, confidence_df
