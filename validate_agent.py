"""
validate_agent.py — Post-generation AI validation agent.

Runs a second Gemini pass to cross-check every populated cell against
the original document text. Produces a validation report.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from google import genai
from dotenv import load_dotenv

from extract_llm import CaseResult, FieldResult
from parse_docx import CaseText
from schema import COLUMNS

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
    client: genai.Client,
) -> CaseValidation:
    """Validate one case's extractions against source text."""
    prompt = _build_validation_prompt(case, extraction)

    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config={
                "system_instruction": VALIDATION_SYSTEM,
                "temperature": 0.0,
                "response_mime_type": "application/json",
            },
        )
        response_text = response.text
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
    batch_delay: float = 1.0,
) -> list[CaseValidation]:
    """Run validation on all cases."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set.")

    client = genai.Client(api_key=api_key)
    # Build lookup from case_index to CaseText
    case_lookup = {c.case_index: c for c in cases}
    validations = []

    for i, extraction in enumerate(extractions):
        case = case_lookup.get(extraction.case_index)
        if not case:
            continue
        print(f"  [{i + 1}/{len(extractions)}] Validating case {extraction.case_index}...")
        try:
            v = validate_case(case, extraction, client)
            status_icon = {"pass": "OK", "review_needed": "REVIEW", "fail": "FAIL"}
            print(f"         → {status_icon.get(v.overall_status, '?')} ({v.fields_flagged} issues)")
            validations.append(v)
        except Exception as e:
            print(f"         → ERROR: {e}")
            validations.append(CaseValidation(
                case_index=case.case_index,
                issues=[FieldIssue("_system", "error", str(e), "", "critical")],
                overall_status="fail",
                fields_checked=0, fields_ok=0, fields_flagged=1,
            ))
        time.sleep(batch_delay)

    return validations


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
