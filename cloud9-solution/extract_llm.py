"""
extract_llm.py — Gemini-powered extraction with source evidence tracing.

Each extracted field returns {"value", "evidence", "confidence"} so every
cell in the output Excel can be traced back to the original document text.
"""

import json
import os
import time
from dataclasses import dataclass, field

from google import genai
from dotenv import load_dotenv

from parse_docx import CaseText
from schema import COLUMNS, ColumnDef, FIELD_GROUPS

load_dotenv()


@dataclass
class FieldResult:
    """Extraction result for a single field."""
    key: str
    value: str
    evidence: str      # Verbatim quote from source text
    confidence: str    # "high", "medium", "low", "none"


@dataclass
class CaseResult:
    """All extracted fields for one MDT case."""
    case_index: int
    fields: dict[str, FieldResult]   # key -> FieldResult
    raw_llm_response: str
    source_text: str


def _build_field_descriptions() -> str:
    """Build the field definition block for the prompt from schema COLUMNS."""
    lines = []
    current_group = None
    for col in COLUMNS:
        if col.group != current_group:
            current_group = col.group
            lines.append(f"\n### {current_group.replace('_', ' ').title()}")
        lines.append(f'- "{col.key}": {col.extraction_hint}')
    return "\n".join(lines)


FIELD_DESCRIPTIONS = _build_field_descriptions()

SYSTEM_INSTRUCTION = """You are a clinical data extraction specialist for colorectal cancer MDT (Multidisciplinary Team) meeting records. Your job is to extract structured data from MDT case discussion text with full source traceability.

CRITICAL RULES:
1. Extract ONLY information explicitly stated in the source text.
2. For each field, return: {"value": "extracted value", "evidence": "exact verbatim quote from source", "confidence": "high|medium|low|none"}
3. The "evidence" MUST be a character-for-character substring that appears in the SOURCE TEXT. Never paraphrase.
4. If a field's information is not present, return {"value": "", "evidence": "", "confidence": "none"}.
5. A blank value is ALWAYS better than a wrong value. When uncertain, leave blank.
6. Dates must be DD/MM/YYYY format. If only 2-digit year, prepend "20" (e.g. 25 → 2025).
7. For staging values (T, N, M, EMVI, CRM, PSW), extract ONLY the value portion (e.g. "3b" not "T3b", "1c" not "N1c").
8. For EMVI: normalize to "positive" or "negative". Also map "+" to "positive", "-" to "negative".
9. For previous_cancer: answer "Yes" ONLY for cancers other than the current colorectal diagnosis. Default to "No" if no prior cancer is mentioned.
10. For endoscopy_type: classify as "Colonoscopy complete", "incomplete colonoscopy", or "flexi sig".
11. For treatment approach: classify using these mappings:
    - FOXTROT/CAPOX/FOLFOX/neoadjuvant chemo → "downstaging chemotherapy"
    - CRT/chemoradiotherapy/long course → "downstaging nCRT"
    - Short course/SCPRT/5x5 → "downstaging shortcourse RT"
    - Papillon/EBRT → "Papillon +/- EBRT"
    - Surgery/hemicolectomy/resection/anterior resection/right hemi/eLAPE → "straight to surgery"
    - TNT/total neoadjuvant → "TNT"
    - Watch and wait → "watch and wait"
    - If unclear or not yet decided, return ""
12. For M staging from CT: infer "0" from "no metastases"/"no distant disease"/"no liver metastases". Infer "1" from explicit "metastases"/"liver lesions"/"lung metastases".
13. For biopsy_date: if not explicitly stated but biopsy was taken during a dated endoscopy, use the endoscopy date. If endoscopy happened but date unknown, return "Missing".
14. For endoscopy_date: if endoscopy happened but date not stated, return "Missing"."""


def _build_extraction_prompt(case: CaseText) -> str:
    """Build the user prompt with all case sections and field definitions."""
    return f"""Extract all available clinical data from this MDT case.

## SOURCE TEXT
{case.full_text}

## FIELDS TO EXTRACT
{FIELD_DESCRIPTIONS}

Return a single JSON object where each key is the field name and each value is {{"value": "...", "evidence": "...", "confidence": "high|medium|low|none"}}."""


def _parse_response(response_text: str) -> dict[str, FieldResult]:
    """Parse the Gemini JSON response into FieldResult objects."""
    cleaned = response_text.strip()
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            col.key: FieldResult(key=col.key, value="", evidence="", confidence="none")
            for col in COLUMNS
        }

    results = {}
    for col in COLUMNS:
        field_data = data.get(col.key, {})
        if isinstance(field_data, dict):
            results[col.key] = FieldResult(
                key=col.key,
                value=str(field_data.get("value", "") or "").strip(),
                evidence=str(field_data.get("evidence", "") or "").strip(),
                confidence=str(field_data.get("confidence", "none") or "none").strip(),
            )
        elif field_data is not None and str(field_data).strip():
            # LLM returned a plain value instead of dict
            results[col.key] = FieldResult(
                key=col.key,
                value=str(field_data).strip(),
                evidence="",
                confidence="low",
            )
        else:
            results[col.key] = FieldResult(
                key=col.key, value="", evidence="", confidence="none"
            )
    return results


def extract_case(case: CaseText, client: genai.Client) -> CaseResult:
    """Extract all fields from one MDT case using Gemini."""
    prompt = _build_extraction_prompt(case)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "system_instruction": SYSTEM_INSTRUCTION,
            "temperature": 0.0,
            "response_mime_type": "application/json",
        },
    )

    response_text = response.text
    fields = _parse_response(response_text)

    return CaseResult(
        case_index=case.case_index,
        fields=fields,
        raw_llm_response=response_text,
        source_text=case.full_text,
    )


def extract_all_cases(
    cases: list[CaseText],
    batch_delay: float = 1.0,
) -> list[CaseResult]:
    """Extract fields from all cases with rate limiting and progress logging."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Export it or add to .env file.")

    client = genai.Client(api_key=api_key)
    results: list[CaseResult] = []

    for i, case in enumerate(cases):
        print(f"  [{i+1}/{len(cases)}] Extracting case {case.case_index}...")
        try:
            result = extract_case(case, client)
            populated = sum(1 for fr in result.fields.values() if fr.value)
            print(f"         → {populated} fields populated")
            results.append(result)
        except Exception as e:
            print(f"         → ERROR: {e}")
            results.append(CaseResult(
                case_index=case.case_index,
                fields={
                    col.key: FieldResult(key=col.key, value="", evidence="", confidence="none")
                    for col in COLUMNS
                },
                raw_llm_response=f"ERROR: {e}",
                source_text=case.full_text,
            ))

        if i < len(cases) - 1:
            time.sleep(batch_delay)

    return results
