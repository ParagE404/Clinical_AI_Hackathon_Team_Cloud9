"""
validate_and_fix.py — Post-processing validation and correction for LLM extractions.

This module validates LLM-extracted fields against the source text and
attempts to fix common issues like misquoted evidence or missing values.
"""

from typing import Dict, List
from dataclasses import dataclass
from extract_llm import FieldResult, CaseResult


@dataclass
class ValidationIssue:
    field: str
    issue_type: str  # "misquote", "missing_evidence", "incorrect_value"
    description: str
    severity: str  # "critical", "warning"


def validate_evidence_verbatim(field_result: FieldResult, source_text: str) -> ValidationIssue | None:
    """Check if evidence appears verbatim in source text."""
    if not field_result.evidence or not field_result.value:
        return None

    # Check if evidence is actually in source (case-sensitive)
    if field_result.evidence not in source_text:
        # Try to find the closest match
        value_in_source = field_result.value in source_text
        if value_in_source:
            # Value is correct but evidence is wrong - try to find better evidence
            return ValidationIssue(
                field=field_result.key,
                issue_type="misquote",
                description=f"Evidence '{field_result.evidence}' not found verbatim. Value '{field_result.value}' exists but needs better evidence quote.",
                severity="warning"
            )
        else:
            return ValidationIssue(
                field=field_result.key,
                issue_type="incorrect_value",
                description=f"Neither value '{field_result.value}' nor evidence '{field_result.evidence}' found in source.",
                severity="critical"
            )
    return None


def validate_empty_evidence(field_result: FieldResult) -> ValidationIssue | None:
    """Check for values without supporting evidence."""
    if field_result.value and not field_result.evidence:
        return ValidationIssue(
            field=field_result.key,
            issue_type="missing_evidence",
            description=f"Value '{field_result.value}' provided but evidence field is empty.",
            severity="critical" if field_result.confidence == "high" else "warning"
        )
    return None


def validate_case_result(result: CaseResult) -> List[ValidationIssue]:
    """Run all validation checks on a case result."""
    issues = []

    for field_result in result.fields.values():
        # Check verbatim evidence
        issue = validate_evidence_verbatim(field_result, result.source_text)
        if issue:
            issues.append(issue)

        # Check empty evidence
        issue = validate_empty_evidence(field_result)
        if issue:
            issues.append(issue)

    return issues


def auto_fix_evidence(field_result: FieldResult, source_text: str) -> FieldResult:
    """Attempt to auto-fix evidence by finding the exact quote in source text.

    Strategy: Search for the value in source text and extract surrounding context.
    """
    if not field_result.value or field_result.evidence in source_text:
        return field_result  # Already correct

    # Try to find value in source
    value = field_result.value
    if value in source_text:
        # Found it - extract with some context
        idx = source_text.find(value)

        # Look for natural boundaries (sentences, line breaks)
        start = max(0, idx - 50)
        end = min(len(source_text), idx + len(value) + 50)

        # Try to find sentence/line boundaries
        while start > 0 and source_text[start] not in ['\n', '.', ':', ';']:
            start -= 1
        while end < len(source_text) and source_text[end] not in ['\n', '.', ';']:
            end += 1

        evidence = source_text[start:end].strip()

        return FieldResult(
            key=field_result.key,
            value=field_result.value,
            evidence=evidence,
            confidence="medium"  # Downgrade confidence since it's auto-fixed
        )

    return field_result  # Can't fix


def validate_and_fix_batch(results: List[CaseResult]) -> tuple[List[CaseResult], Dict]:
    """Validate and attempt to fix all cases.

    Returns:
        - List of corrected CaseResult objects
        - Dict with validation statistics
    """
    corrected_results = []
    stats = {
        "total_cases": len(results),
        "cases_with_issues": 0,
        "total_issues": 0,
        "critical_issues": 0,
        "auto_fixed": 0
    }

    for result in results:
        issues = validate_case_result(result)

        if issues:
            stats["cases_with_issues"] += 1
            stats["total_issues"] += len(issues)
            stats["critical_issues"] += sum(1 for i in issues if i.severity == "critical")

            # Attempt auto-fix
            corrected_fields = {}
            for key, field_result in result.fields.items():
                fixed = auto_fix_evidence(field_result, result.source_text)
                if fixed != field_result:
                    stats["auto_fixed"] += 1
                corrected_fields[key] = fixed

            # Create corrected result
            corrected_results.append(CaseResult(
                case_index=result.case_index,
                fields=corrected_fields,
                raw_llm_response=result.raw_llm_response,
                source_text=result.source_text,
                regex_field_count=result.regex_field_count,
                llm_field_count=result.llm_field_count
            ))
        else:
            corrected_results.append(result)

    return corrected_results, stats
