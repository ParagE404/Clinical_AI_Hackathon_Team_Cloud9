"""
parse_docx.py — Deterministic DOCX parser for MDT proformas.

Walks the XML body elements to maintain paragraph/table interleaving,
then extracts raw text per case table with row-level markers.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass
class CaseText:
    """Raw text segments extracted from one MDT case table."""
    case_index: int
    mdt_date_paragraph: str   # Text of paragraph before the table
    demographics_text: str    # Row 1 text (patient details data)
    staging_text: str         # Row 3 text (diagnosis, ICD10, differentiation)
    clinical_text: str        # Row 5 text (symptoms, imaging, endoscopy)
    outcome_text: str         # Row 7 text (MDT decision)
    full_text: str            # All rows concatenated with [ROW N]: markers
    row_texts: dict = field(default_factory=dict)  # row_index -> raw text


def _dedupe_row_text(row) -> str:
    """Extract text from a table row, deduplicating merged cells."""
    seen = set()
    parts = []
    for cell in row.cells:
        cell_text = "\n".join(p.text for p in cell.paragraphs).strip()
        if cell_text and cell_text not in seen:
            parts.append(cell_text)
            seen.add(cell_text)
    return "\n".join(parts)


def _is_proforma_table(table: Table) -> bool:
    """Check if a table is an MDT proforma (has 'Patient Details' in header row)."""
    if not table.rows or len(table.rows) < 2:
        return False
    header_text = _dedupe_row_text(table.rows[0])
    return "Patient Details" in header_text


_MDT_DATE_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE
)


def parse_docx(file_path: str | Path) -> list[CaseText]:
    """
    Parse the MDT proforma DOCX and return a list of CaseText objects.

    Walks XML body children directly to maintain paragraph/table order,
    so we can capture the paragraph text before each table.
    """
    doc = Document(str(file_path))
    body = doc.element.body

    # Build ordered list of (type, element) preserving document order
    elements: list[tuple[str, object]] = []
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            elements.append(("para", Paragraph(child, doc)))
        elif tag == "tbl":
            elements.append(("table", Table(child, doc)))

    cases: list[CaseText] = []
    last_para_text = ""

    for kind, elem in elements:
        if kind == "para":
            text = elem.text.strip()
            if text:
                last_para_text = text
        elif kind == "table":
            table: Table = elem
            if not _is_proforma_table(table):
                continue

            # Extract text from each row
            row_texts: dict[int, str] = {}
            for row_idx, row in enumerate(table.rows):
                text = _dedupe_row_text(row)
                if text:
                    row_texts[row_idx] = text

            # Build full_text with row markers for evidence tracing
            full_text = "\n\n".join(
                f"[ROW {r}]: {text}" for r, text in sorted(row_texts.items())
            )

            # Add MDT date paragraph context
            if last_para_text:
                full_text = f"[MDT HEADER]: {last_para_text}\n\n{full_text}"

            cases.append(CaseText(
                case_index=len(cases),
                mdt_date_paragraph=last_para_text,
                demographics_text=row_texts.get(1, ""),
                staging_text=row_texts.get(3, ""),
                clinical_text=row_texts.get(5, ""),
                outcome_text=row_texts.get(7, ""),
                full_text=full_text,
                row_texts=row_texts,
            ))

    return cases


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "../data/hackathon-mdt-outcome-proformas.docx"
    cases = parse_docx(path)
    print(f"Parsed {len(cases)} cases\n")
    for c in cases[:3]:
        print(f"=== Case {c.case_index} ===")
        print(f"MDT paragraph: {c.mdt_date_paragraph[:100]}")
        print(f"Demographics: {c.demographics_text[:100]}")
        print(f"Staging: {c.staging_text[:100]}")
        print(f"Clinical: {c.clinical_text[:100]}")
        print(f"Outcome: {c.outcome_text[:100]}")
        print()
