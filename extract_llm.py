"""
extract_llm.py — LLM-powered extraction with source evidence tracing.

Each extracted field returns {"value", "evidence", "confidence"} so every
cell in the output Excel can be traced back to the original document text.

Supports both local LLMs (Ollama) and cloud LLMs (Gemini) via llm_client abstraction.
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass, field

from dotenv import load_dotenv

from parse_docx import CaseText
from schema import COLUMNS, ColumnDef, FIELD_GROUPS
from llm_client import LLMClient

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
    regex_field_count: int = 0       # Number of fields extracted via regex
    llm_field_count: int = 0         # Number of fields extracted via LLM


def _build_field_descriptions(skip_keys: set | None = None) -> str:
    """Build the field definition block for the prompt from schema COLUMNS.

    Args:
        skip_keys: Optional set of field keys to omit from the prompt because
                   they have already been extracted by the regex pre-pass.
    """
    skip_keys = skip_keys or set()
    lines = []
    current_group = None
    for col in COLUMNS:
        if col.key in skip_keys:
            continue
        if col.group != current_group:
            current_group = col.group
            lines.append(f"\n### {current_group.replace('_', ' ').title()}")
        lines.append(f'- "{col.key}": {col.extraction_hint}')
    return "\n".join(lines)


FIELD_DESCRIPTIONS = _build_field_descriptions()

SYSTEM_INSTRUCTION = """You are a clinical data extraction specialist for colorectal cancer MDT (Multidisciplinary Team) meeting records. Your job is to extract structured data from MDT case discussion text with full source traceability.

DOCUMENT STRUCTURE — MDT proformas have these sections:
- [MDT HEADER]: Contains the meeting date.
- [ROW 1]: Patient demographics — Hospital Number, NHS Number, Name, Gender, DOB.
- [ROW 3]: Staging & Diagnosis — Diagnosis text, ICD10 code, differentiation, staging fields.
- [ROW 5]: Clinical Details — Symptoms, history, imaging reports (CT, MRI), endoscopy findings. This section often contains MRI staging lines like "MRI pelvis on DD/MM/YYYY: T__, N__, CRM __, EMVI __" and CT reports like "CT TAP on DD/MM/YYYY: ..."
- [ROW 7]: MDT Outcome — The MDT decision, may also contain additional imaging results and treatment plans.

CRITICAL RULES:
1. Extract ONLY information explicitly stated in the source text.
2. For each field, return: {"value": "extracted value", "evidence": "exact verbatim quote from source", "confidence": "high|medium|low|none"}
3. The "evidence" MUST be a verbatim substring from the SOURCE TEXT. Never paraphrase.
4. If a field's information is not present, return {"value": "", "evidence": "", "confidence": "none"}.
5. A blank value is ALWAYS better than a wrong value. When uncertain, leave blank.

DATE RULES:
6. Dates must be DD/MM/YYYY format. Convert 2-digit years: prepend "20" (e.g. 25 → 2025, 24 → 2024).
7. Convert dates like "4/3/25" → "04/03/2025", "22/2/2025" → "22/02/2025".

STAGING RULES:
8. For T, N staging: extract ONLY the value after the prefix (e.g. "T3b" → "3b", "N1c" → "1c", "T2" → "2", "N0" → "0").
9. For EMVI: normalize to "positive" or "negative". Map "+" → "positive", "-" → "negative", "–" (dash) → "negative".
10. For CRM: normalize to "clear", "involved", or "threatened". Map "unsafe" → "threatened", "-" or "–" (dash) → "clear".
11. For PSW: normalize to "clear" or "unsafe". Map "-" or "–" (dash) → "clear".
12. MRI staging can appear in BOTH [ROW 5] (Clinical Details) and [ROW 7] (MDT Outcome). Check both.
13. For CT M staging: infer "0" from "no metastases"/"no distant disease"/"no distant metastases"/"no liver metastases"/"no mets". Infer "1" from "metastases"/"liver lesions"/"lung metastases"/"metastatic disease".
14. CT staging may be embedded in free text like "CT TAP: sigmoid thickening, no metastases" or simply "CT: no mets" — extract what you can. If a CT is mentioned with findings but no date, set the CT date to "Missing".

DEMOGRAPHICS RULES:
15. For initials: first letter of first name + first letter of last name (e.g. "AIDEN O'CONNOR" → "AO", "Ziad Al-Farsi" → "ZA").
16. For previous_cancer: answer "Yes" ONLY for cancers OTHER than the current colorectal diagnosis. History of breast cancer, prostate cancer, lymphoma, head and neck cancer etc. = "Yes". If no prior cancer mentioned, answer "No".
17. For previous_cancer_site: state the site (e.g. "breast", "lymphoma", "prostate"). "N/A" if previous_cancer is "No".

ENDOSCOPY/HISTOLOGY RULES:
18. For endoscopy_type: classify as "Colonoscopy complete" (if colonoscopy reaches ileocaecal valve, described as complete, or simply described as "Colonoscopy" with findings — default to "Colonoscopy complete" unless explicitly stated as incomplete), "incomplete colonoscopy" (only if explicitly stated as incomplete), or "flexi sig" (flexible sigmoidoscopy / flexi sig). IMPORTANT: If the text says "Colonoscopy: findings..." or "Colonoscopy – findings...", classify as "Colonoscopy complete". If text says "Flexi sig: findings..." or "flexi sig" with findings, classify as "flexi sig".
19. For endoscopy_date: if endoscopy happened but no date given, return "Missing".
20. For biopsy_result: look in both [ROW 3] Diagnosis field AND [ROW 7] Outcome for histology results.
21. For biopsy_date: if not explicitly stated but biopsy was during a dated endoscopy, use that date. If date unknown, return "Missing".

TREATMENT APPROACH RULES:
22. Classify the MDT decision using these exact mappings:
    - FOXTROT/CAPOX/FOLFOX/neoadjuvant chemotherapy → "downstaging chemotherapy"
    - CRT/chemoradiotherapy/long course radiotherapy/neoadjuvant CRT → "downstaging nCRT"
    - Short course radiotherapy/SCPRT/5x5Gy → "downstaging shortcourse RT"
    - TNT (and then specifying CRT first or chemo first) → "TNT"
    - Papillon/contact radiotherapy/EBRT → "Papillon +/- EBRT"
    - Surgery/hemicolectomy/resection/anterior resection/right hemicolectomy/eLAPE/surgical review/refer for surgical review/ESD/local excision/TEMS/TAMIS → "straight to surgery"
    - Watch and wait/active surveillance → "watch and wait"
    - If the outcome is for further investigations only (e.g. "for colonoscopy", "for MRI", "rediscuss"), return ""
23. Look in [ROW 7] (MDT Outcome) for the treatment decision.

IMPORTANT — SEARCH THOROUGHLY:
- Clinical data is spread across ALL rows. MRI data may be in [ROW 5] OR [ROW 7]. CT data may be in [ROW 5] OR [ROW 7].
- The [ROW 7] MDT Outcome often contains imaging results AND the treatment decision together.
- Extract ALL available data from every row. Do not stop at one section."""


def _build_extraction_prompt(case: CaseText, skip_keys: set | None = None) -> str:
    """Build the user prompt with all case sections and field definitions.

    Args:
        case: The parsed case text.
        skip_keys: Optional set of field keys already extracted by regex;
                   these are omitted from the LLM field list to save tokens.
    """
    field_desc = _build_field_descriptions(skip_keys)
    return f"""Extract all available clinical data from this MDT case. Search ALL sections thoroughly — imaging results and staging data can appear in Clinical Details (ROW 5) OR MDT Outcome (ROW 7) or both.

## SOURCE TEXT
{case.full_text}

## FIELDS TO EXTRACT
{field_desc}

Return a single JSON object where each key is the field name and each value is {{"value": "...", "evidence": "...", "confidence": "high|medium|low|none"}}.
For fields not found in the text, return {{"value": "", "evidence": "", "confidence": "none"}}."""


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


def extract_case(case: CaseText, client: LLMClient, max_retries: int = 2) -> CaseResult:
    """Extract all fields from one MDT case using LLM with retry logic.

    Fields that can be extracted deterministically via regex are pre-filled
    before the LLM call, which reduces token usage and hallucination risk.
    """
    thread_id = threading.get_ident()
    start_time = time.time()

    # 1. Run regex pre-extraction (zero API cost, deterministic)
    from extract_regex import regex_extract  # lazy import avoids circular dependency
    pre_filled = regex_extract(case)
    skip_keys = set(pre_filled.keys())

    # 2. Build prompt excluding pre-filled keys
    prompt = _build_extraction_prompt(case, skip_keys=skip_keys)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            api_start = time.time()
            response = client.generate(
                prompt=prompt,
                system_instruction=SYSTEM_INSTRUCTION,
                json_mode=True,
            )
            api_time = time.time() - api_start

            response_text = response["text"]
            llm_fields = _parse_response(response_text)

            # 3. Merge: regex results take priority over LLM results
            merged = {**llm_fields, **pre_filled}

            # 4. Count fields with non-empty values from each source
            regex_count = sum(1 for fr in pre_filled.values() if fr.value)
            llm_count = sum(1 for key, fr in llm_fields.items() if fr.value and key not in skip_keys)

            elapsed = time.time() - start_time
            print(f"[Thread {thread_id}] Case {case.case_index}: completed in {elapsed:.2f}s (API: {api_time:.2f}s)")

            return CaseResult(
                case_index=case.case_index,
                fields=merged,
                raw_llm_response=response_text,
                source_text=case.full_text,
                regex_field_count=regex_count,
                llm_field_count=llm_count,
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
                continue
            raise last_error


def extract_all_cases(
    cases: list[CaseText],
    batch_delay: float = 0.0,
    max_workers: int = 5,
) -> list[CaseResult]:
    """Extract fields from all cases with parallel processing and progress logging.

    Args:
        cases: List of CaseText objects to extract.
        batch_delay: Delay between API calls (deprecated, kept for compatibility).
        max_workers: Maximum number of parallel worker threads.

    Returns:
        List of CaseResult objects in the same order as input cases.
    """
    # Initialize LLM client (automatically selects provider from env vars)
    client = LLMClient()
    print(f"Using LLM: {client}")
    print(f"Parallel extraction: {max_workers} worker threads")

    results: list[CaseResult | None] = [None] * len(cases)
    pipeline_start = time.time()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Submit all tasks with their index
        futures = {
            pool.submit(extract_case, case, client): (i, case)
            for i, case in enumerate(cases)
        }

        # Process results as they complete
        for future in as_completed(futures):
            i, case = futures[future]
            try:
                result = future.result()
                populated = sum(1 for fr in result.fields.values() if fr.value)
                print(f"  [{i+1}/{len(cases)}] Extracting case {case.case_index}...")
                print(f"         → {populated} fields populated (regex: {result.regex_field_count}, LLM: {result.llm_field_count})")
                results[i] = result
            except Exception as e:
                print(f"  [{i+1}/{len(cases)}] Extracting case {case.case_index}...")
                print(f"         → ERROR: {e}")
                results[i] = CaseResult(
                    case_index=case.case_index,
                    fields={
                        col.key: FieldResult(key=col.key, value="", evidence="", confidence="none")
                        for col in COLUMNS
                    },
                    raw_llm_response=f"ERROR: {e}",
                    source_text=case.full_text,
                    regex_field_count=0,
                    llm_field_count=0,
                )

    pipeline_time = time.time() - pipeline_start
    print(f"\nPipeline completed in {pipeline_time:.2f}s total")
    print(f"Average time per case: {pipeline_time/len(cases):.2f}s")

    return results
