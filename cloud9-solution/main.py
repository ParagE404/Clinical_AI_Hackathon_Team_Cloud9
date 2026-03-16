"""
main.py — Cloud9 MDT Extraction Pipeline

Usage:
    python main.py                       # Full pipeline (50 cases + validation)
    python main.py --skip-validation     # Skip the validation agent pass
    python main.py --cases 0-4           # Process only cases 0 through 4
    python main.py --cases 0,5,10        # Process specific cases
    python main.py --from-json           # Rebuild Excel from existing raw-extractions.json
"""

import argparse
import json
import time
from pathlib import Path

from parse_docx import parse_docx
from extract_llm import extract_all_cases, CaseResult, FieldResult
from build_dataframe import build_dataframes
from write_excel import write_styled_workbook
from schema import COLUMNS

# ── Path configuration ──
ROOT_DIR = Path(__file__).resolve().parent.parent
DOCX_INPUT = ROOT_DIR / "data" / "hackathon-mdt-outcome-proformas.docx"
PROTOTYPE_WORKBOOK = ROOT_DIR / "data" / "hackathon-database-prototype.xlsx"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_WORKBOOK = OUTPUT_DIR / "generated-database-cloud9.xlsx"
VALIDATION_REPORT = OUTPUT_DIR / "validation-report.json"
RAW_EXTRACTIONS = OUTPUT_DIR / "raw-extractions.json"


def _load_extractions_from_json(json_path: Path) -> list:
    """Reload CaseResult objects from a previous raw-extractions.json."""
    with open(json_path) as f:
        raw_data = json.load(f)

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
                    key=col.key, value="", evidence="", confidence="none"
                )
        results.append(CaseResult(
            case_index=case_data["case_index"],
            fields=fields,
            raw_llm_response="(loaded from JSON)",
            source_text="",
        ))
    return results


def main():
    parser = argparse.ArgumentParser(description="Cloud9 MDT Extraction Pipeline")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Skip the validation agent pass")
    parser.add_argument("--cases", type=str, default=None,
                        help="Case range: '0-4' or '0,5,10'")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Delay between API calls in seconds (default: 1.0)")
    parser.add_argument("--from-json", action="store_true",
                        help="Rebuild Excel from existing raw-extractions.json (skip LLM)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ════════════════════════════════════════════════════
    # STAGE 1: Parse DOCX
    # ════════════════════════════════════════════════════
    print("=" * 60)
    print("STAGE 1: Parsing DOCX...")
    print("=" * 60)
    all_cases = parse_docx(DOCX_INPUT)
    print(f"  Parsed {len(all_cases)} cases from DOCX.")

    # Filter cases if requested
    cases = all_cases
    if args.cases:
        if "-" in args.cases:
            start, end = map(int, args.cases.split("-"))
            cases = [c for c in all_cases if start <= c.case_index <= end]
        else:
            indices = set(map(int, args.cases.split(",")))
            cases = [c for c in all_cases if c.case_index in indices]
        print(f"  Filtered to {len(cases)} cases.")

    # ════════════════════════════════════════════════════
    # STAGE 2: LLM Extraction (or reload from JSON)
    # ════════════════════════════════════════════════════
    if args.from_json:
        print("\n" + "=" * 60)
        print("STAGE 2: Loading extractions from JSON...")
        print("=" * 60)
        extractions = _load_extractions_from_json(RAW_EXTRACTIONS)
        if args.cases:
            case_indices = {c.case_index for c in cases}
            extractions = [e for e in extractions if e.case_index in case_indices]
        print(f"  Loaded {len(extractions)} extractions from {RAW_EXTRACTIONS}")
    else:
        print("\n" + "=" * 60)
        print("STAGE 2: Extracting fields with Gemini...")
        print("=" * 60)
        t0 = time.time()
        extractions = extract_all_cases(cases, batch_delay=args.delay)
        elapsed = time.time() - t0
        print(f"\n  Extraction complete in {elapsed:.1f}s.")

        # Save raw extractions for debugging
        raw_data = []
        for ext in extractions:
            case_data = {"case_index": ext.case_index, "fields": {}}
            for key, fr in ext.fields.items():
                case_data["fields"][key] = {
                    "value": fr.value,
                    "evidence": fr.evidence,
                    "confidence": fr.confidence,
                }
            raw_data.append(case_data)
        with open(RAW_EXTRACTIONS, "w") as f:
            json.dump(raw_data, f, indent=2)
        print(f"  Raw extractions saved to {RAW_EXTRACTIONS}")

    # ════════════════════════════════════════════════════
    # STAGE 3: Build DataFrames
    # ════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("STAGE 3: Building DataFrames...")
    print("=" * 60)
    data_df, evidence_df, confidence_df = build_dataframes(extractions)
    non_empty = data_df.notna().sum().sum()
    total_cells = data_df.shape[0] * data_df.shape[1]
    print(f"  DataFrame shape: {data_df.shape}")
    print(f"  Non-empty cells: {non_empty} / {total_cells} ({100*non_empty/total_cells:.1f}%)")
    print(f"  Baseline best: 675 cells → our improvement: {non_empty - 675:+d}")

    # ════════════════════════════════════════════════════
    # STAGE 4: Write Excel
    # ════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("STAGE 4: Writing Excel workbook...")
    print("=" * 60)
    write_styled_workbook(
        data_df, evidence_df, confidence_df,
        PROTOTYPE_WORKBOOK, OUTPUT_WORKBOOK,
    )
    print(f"  Workbook saved to {OUTPUT_WORKBOOK}")
    print(f"  → Sheet 1: Patient data (with cell comments for evidence)")
    print(f"  → Sheet 2: Evidence Map (full audit trail)")

    # ════════════════════════════════════════════════════
    # STAGE 5: Validation Agent
    # ════════════════════════════════════════════════════
    if not args.skip_validation:
        print("\n" + "=" * 60)
        print("STAGE 5: Running validation agent...")
        print("=" * 60)
        from validate_agent import validate_all, generate_validation_report
        validations = validate_all(cases, extractions, batch_delay=args.delay)
        report = generate_validation_report(validations, str(VALIDATION_REPORT))
        print(f"\n  Validation report saved to {VALIDATION_REPORT}")
        print(f"  Results: {report['passed']} passed, "
              f"{report['review_needed']} need review, "
              f"{report['failed']} failed")
        print(f"  Total issues: {report['total_issues']} "
              f"({report['critical_issues']} critical)")
    else:
        print("\n  Validation skipped (--skip-validation flag).")

    # ════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\n  Output: {OUTPUT_WORKBOOK}")
    if not args.skip_validation:
        print(f"  Validation: {VALIDATION_REPORT}")
    print(f"  Raw data: {RAW_EXTRACTIONS}")


if __name__ == "__main__":
    main()
