"""
validate_agent.py — Post-generation AI validation agent.

Runs a second LLM pass to cross-check every populated cell against
the original document text. Produces a validation report.

Supports both local LLMs (Ollama) and cloud LLMs (Gemini) via llm_client abstraction.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv

from extract_llm import CaseResult, FieldResult
from parse_docx import CaseText
from schema import COLUMNS
from llm_client import LLMClient

load_dotenv()

VALIDATION_SYSTEM = """You are a clinical data validation specialist. Your task is to verify AI-extracted data against the original MDT source document.

For each extracted field, check:
1. Does the "evidence" quote ACTUALLY appear verbatim in the source text? Flag misquotes.
2. Is the "value" correctly derived from the "evidence"? Flag incorrect interpretations.
3. Are there important fields that are EMPTY but have data in the source text? Flag missed extractions.

Only report ACTUAL issues. Focus on: patient identifiers, staging values, dates, and clinical decisions."""


@dataclass
class FieldIssue:
    field_key: str
    issue_type: str   # "hallucination", "misquote", "incorrect_value", "missing_data"
    description: str
    suggested_value: str
    severity: str     # "critical", "warning", "info"


@dataclass
class CaseValidation:
    case_index: int
    issues: list[FieldIssue]
    overall_status: str  # "pass", "review_needed", "fail"
    fields_checked: int
    fields_ok: int
    fields_flagged: int


def _build_validation_prompt(case: CaseText, extraction: CaseResult) -> str:
    fields_block = []
    for col in COLUMNS:
        fr = extraction.fields.get(col.key)
        if fr and fr.value:
            fields_block.append(
                f'  "{col.key}": {{"value": {json.dumps(fr.value)}, "evidence": {json.dumps(fr.evidence)}}}'
            )

    fields_json = "{\n" + ",\n".join(fields_block) + "\n}"

    return f"""Verify these AI-extracted fields against the original source document.

## ORIGINAL SOURCE TEXT
{case.full_text}

## EXTRACTED DATA TO VALIDATE
{fields_json}

For each field, check:
1. Does the "evidence" appear verbatim in the source text?
2. Is the "value" correct given the evidence?
3. Are there fields that SHOULD be populated but are empty?

Return a JSON array of issues. Each issue:
{{"field_key": "...", "issue_type": "hallucination|misquote|incorrect_value|missing_data", "description": "...", "suggested_value": "...", "severity": "critical|warning|info"}}

Only report fields with ACTUAL issues. Return empty array [] if all fields are correct."""


def validate_case(
    case: CaseText,
    extraction: CaseResult,
    client: LLMClient,
) -> CaseValidation:
    """Validate one case's extractions against source text."""
    prompt = _build_validation_prompt(case, extraction)

    try:
        response = client.generate(
            prompt=prompt,
            system_instruction=VALIDATION_SYSTEM,
            json_mode=True,
        )
        response_text = response["text"]
    except Exception as e:
        return CaseValidation(
            case_index=case.case_index,
            issues=[FieldIssue("_system", "error", str(e), "", "critical")],
            overall_status="fail",
            fields_checked=0, fields_ok=0, fields_flagged=1,
        )

    # Parse response
    try:
        issues_data = json.loads(response_text.strip())
    except json.JSONDecodeError:
        issues_data = []

    # Convert to FieldIssue objects (skip "ok" entries)
    issues = []
    if isinstance(issues_data, list):
        for item in issues_data:
            if isinstance(item, dict) and item.get("issue_type", "ok") != "ok":
                issues.append(FieldIssue(
                    field_key=item.get("field_key", "unknown"),
                    issue_type=item.get("issue_type", "unknown"),
                    description=item.get("description", ""),
                    suggested_value=item.get("suggested_value", ""),
                    severity=item.get("severity", "info"),
                ))

    populated = sum(1 for fr in extraction.fields.values() if fr.value)

    return CaseValidation(
        case_index=extraction.case_index,
        issues=issues,
        overall_status="pass" if not issues else (
            "fail" if any(i.severity == "critical" for i in issues) else "review_needed"
        ),
        fields_checked=populated,
        fields_ok=populated - len(issues),
        fields_flagged=len(issues),
    )


def validate_all(
    cases: list[CaseText],
    extractions: list[CaseResult],
    batch_delay: float = 0.0,
    max_workers: int = 5,
) -> list[CaseValidation]:
    """Run validation on all cases with parallel processing.

    Args:
        cases: List of CaseText objects.
        extractions: List of CaseResult objects.
        batch_delay: Delay between API calls (deprecated, kept for compatibility).
        max_workers: Maximum number of parallel worker threads.

    Returns:
        List of CaseValidation objects in the same order as extractions.
    """
    # Initialize LLM client (automatically selects provider from env vars)
    client = LLMClient()

    # Build lookup from case_index to CaseText
    case_lookup = {c.case_index: c for c in cases}
    validations: list[CaseValidation | None] = [None] * len(extractions)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Submit all tasks with their index
        futures = {}
        for i, extraction in enumerate(extractions):
            case = case_lookup.get(extraction.case_index)
            if case:
                futures[pool.submit(validate_case, case, extraction, client)] = (i, extraction)

        # Process results as they complete
        for future in as_completed(futures):
            i, extraction = futures[future]
            print(f"  [{i + 1}/{len(extractions)}] Validating case {extraction.case_index}...")
            try:
                v = future.result()
                status_icon = {"pass": "OK", "review_needed": "REVIEW", "fail": "FAIL"}
                print(f"         → {status_icon.get(v.overall_status, '?')} ({v.fields_flagged} issues)")
                validations[i] = v
            except Exception as e:
                print(f"         → ERROR: {e}")
                validations[i] = CaseValidation(
                    case_index=extraction.case_index,
                    issues=[FieldIssue("_system", "error", str(e), "", "critical")],
                    overall_status="fail",
                    fields_checked=0, fields_ok=0, fields_flagged=1,
                )

    # Filter out None values (cases where case_lookup failed)
    return [v for v in validations if v is not None]


def generate_validation_report(
    validations: list[CaseValidation],
    output_path: str,
) -> dict:
    """Generate a JSON validation summary report."""
    summary = {
        "total_cases": len(validations),
        "passed": sum(1 for v in validations if v.overall_status == "pass"),
        "review_needed": sum(1 for v in validations if v.overall_status == "review_needed"),
        "failed": sum(1 for v in validations if v.overall_status == "fail"),
        "total_issues": sum(len(v.issues) for v in validations),
        "critical_issues": sum(
            sum(1 for i in v.issues if i.severity == "critical") for v in validations
        ),
        "cases": [],
    }

    for v in validations:
        summary["cases"].append({
            "case_index": v.case_index,
            "status": v.overall_status,
            "fields_checked": v.fields_checked,
            "fields_ok": v.fields_ok,
            "fields_flagged": v.fields_flagged,
            "issues": [
                {
                    "field": i.field_key,
                    "type": i.issue_type,
                    "description": i.description,
                    "suggested_value": i.suggested_value,
                    "severity": i.severity,
                }
                for i in v.issues
            ],
        })

    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


# ════════════════════════════════════════════════════════════
# Fix Agent — re-extract flagged fields using validation feedback
# ════════════════════════════════════════════════════════════

FIX_SYSTEM = """You are a clinical data extraction correction specialist. You are given:
1. The original MDT source text.
2. A list of fields that were flagged during validation, along with the issue type, description, and a suggested correction.

Your job is to re-extract ONLY the flagged fields, producing corrected values with proper verbatim evidence from the source text.

RULES:
- The "evidence" MUST be a verbatim substring from the SOURCE TEXT. Never paraphrase.
- If a field's information is truly not present in the source text, return {"value": "", "evidence": "", "confidence": "none"}.
- A blank value is ALWAYS better than a wrong value.
- For "missing_data" issues: search the source text carefully for the relevant information.
- For "hallucination" issues: verify data actually exists in source; if not, return blank.
- For "misquote" issues: find the correct verbatim quote from the source text.
- For "incorrect_value" issues: re-derive the value from the correct evidence.
- Return a JSON object with ONLY the flagged field keys."""


def _build_fix_prompt(
    case: CaseText,
    extraction: CaseResult,
    validation: CaseValidation,
) -> str:
    """Build a prompt for the fix agent to correct flagged fields."""
    issues_block = []
    for issue in validation.issues:
        if issue.field_key == "_system":
            continue
        current = extraction.fields.get(issue.field_key)
        current_value = current.value if current else ""
        current_evidence = current.evidence if current else ""
        issues_block.append(
            f'  "{issue.field_key}": {{\n'
            f'    "current_value": {json.dumps(current_value)},\n'
            f'    "current_evidence": {json.dumps(current_evidence)},\n'
            f'    "issue_type": "{issue.issue_type}",\n'
            f'    "description": {json.dumps(issue.description)},\n'
            f'    "suggested_value": {json.dumps(issue.suggested_value)}\n'
            f'  }}'
        )

    issues_json = "{\n" + ",\n".join(issues_block) + "\n}"

    return f"""Re-extract ONLY the flagged fields below, correcting the issues found during validation.

## ORIGINAL SOURCE TEXT
{case.full_text}

## FLAGGED FIELDS WITH ISSUES
{issues_json}

For each flagged field, return a corrected extraction:
{{"field_key": {{"value": "corrected value", "evidence": "exact verbatim quote from source", "confidence": "high|medium|low|none"}}}}

Return ONLY the flagged fields as a JSON object. Do NOT include unflagged fields."""


def fix_case(
    case: CaseText,
    extraction: CaseResult,
    validation: CaseValidation,
    client: LLMClient,
) -> CaseResult:
    """Re-extract flagged fields for one case using validation feedback."""
    # Skip cases with no actionable issues
    actionable = [i for i in validation.issues if i.field_key != "_system"]
    if not actionable:
        return extraction

    prompt = _build_fix_prompt(case, extraction, validation)

    try:
        response = client.generate(
            prompt=prompt,
            system_instruction=FIX_SYSTEM,
            json_mode=True,
        )
        response_text = response["text"]
    except Exception as e:
        print(f"         → Fix API error: {e}")
        return extraction

    # Parse the corrected fields
    try:
        fixes = json.loads(response_text.strip())
    except json.JSONDecodeError:
        return extraction

    if not isinstance(fixes, dict):
        return extraction

    # Merge fixes into a copy of the existing fields
    updated_fields = dict(extraction.fields)
    fixed_count = 0
    for key, fix_data in fixes.items():
        if key not in updated_fields:
            continue
        if not isinstance(fix_data, dict):
            continue
        new_value = str(fix_data.get("value", "") or "").strip()
        new_evidence = str(fix_data.get("evidence", "") or "").strip()
        new_confidence = str(fix_data.get("confidence", "medium") or "medium").strip()
        old = updated_fields[key]
        if new_value != old.value or new_evidence != old.evidence:
            updated_fields[key] = FieldResult(
                key=key,
                value=new_value,
                evidence=new_evidence,
                confidence=new_confidence,
            )
            fixed_count += 1

    return CaseResult(
        case_index=extraction.case_index,
        fields=updated_fields,
        raw_llm_response=extraction.raw_llm_response,
        source_text=extraction.source_text,
    )


def fix_all(
    cases: list[CaseText],
    extractions: list[CaseResult],
    validations: list[CaseValidation],
    batch_delay: float = 0.0,
    max_workers: int = 5,
) -> list[CaseResult]:
    """Fix all cases that have validation issues with parallel processing.

    Args:
        cases: List of CaseText objects.
        extractions: List of CaseResult objects.
        validations: List of CaseValidation objects.
        batch_delay: Delay between API calls (deprecated, kept for compatibility).
        max_workers: Maximum number of parallel worker threads.

    Returns:
        Updated list of CaseResult objects.
    """
    # Initialize LLM client (automatically selects provider from env vars)
    client = LLMClient()

    case_lookup = {c.case_index: c for c in cases}
    val_lookup = {v.case_index: v for v in validations}
    ext_lookup = {e.case_index: e for e in extractions}

    # Identify cases that need fixing
    to_fix = [v for v in validations if v.overall_status in ("fail", "review_needed")
              and any(i.field_key != "_system" for i in v.issues)]

    if not to_fix:
        print("  No cases need fixing.")
        return extractions

    print(f"  {len(to_fix)} cases need fixing.")

    updated = list(extractions)
    ext_index = {e.case_index: idx for idx, e in enumerate(extractions)}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Submit all fix tasks
        futures = {}
        for i, val in enumerate(to_fix):
            case = case_lookup.get(val.case_index)
            ext = ext_lookup.get(val.case_index)
            if case and ext:
                futures[pool.submit(fix_case, case, ext, val, client)] = (i, val, ext)

        # Process results as they complete
        for future in as_completed(futures):
            i, val, ext = futures[future]
            issue_count = len([j for j in val.issues if j.field_key != "_system"])
            print(f"  [{i + 1}/{len(to_fix)}] Fixing case {val.case_index} ({issue_count} issues)...")

            try:
                fixed = future.result()
                changed = sum(
                    1 for k in fixed.fields
                    if fixed.fields[k].value != ext.fields.get(k, FieldResult(k, "", "", "none")).value
                )
                print(f"         → {changed} fields corrected")
                idx = ext_index.get(val.case_index)
                if idx is not None:
                    updated[idx] = fixed
            except Exception as e:
                print(f"         → ERROR: {e}")

    return updated
