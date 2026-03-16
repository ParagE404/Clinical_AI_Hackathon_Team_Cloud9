# Schema Design — Team Cloud9

> **Purpose**: This document defines the extraction schema, confidence scoring system,
> evidence linking format, output structure, and field-level decisions for the Team Cloud9
> MDT extraction pipeline. Every team member should read this before writing code.

---

## 1. Core Principle: Transparency Over Completeness

A blank cell is **always better than a wrong cell** in a clinical context.
If the document does not contain evidence for a field, leave it empty.
Never guess. Let the confidence system communicate uncertainty instead.

---

## 2. Field Priority Tiers

Not all 88 columns are equally important or equally extractable.
Work in priority order — do not move to P1 until P0 is solid.

### P0 — Must Have (present in every case)
| Column | Source in Doc | Extraction Method |
|--------|--------------|-------------------|
| Demographics: DOB | Patient Details table, row 2 | Regex |
| Demographics: Initials | Patient name in row 2 | Derived (first+last initial) |
| Demographics: MRN | `Hospital Number:` in row 2 | Regex |
| Demographics: NHS Number | `NHS Number:` in row 2 | Regex |
| Demographics: Gender | `Male`/`Female` in row 2 | Regex |
| Histology: Biopsy result | `Diagnosis:` in Staging/Diagnosis row | Regex |
| Histology: MMR status | `MMR deficient/proficient` anywhere | Regex |
| Baseline MRI: date | `MRI [qualifier] on DATE` in Clinical Details | Regex |
| Baseline MRI: mrT/mrN/mrEMVI/mrCRM/mrPSW | MRI segment text | Regex |
| Baseline CT: Date | `CT [qualifier] on DATE` in Clinical Details | Regex |
| Baseline CT: T/N/M/EMVI | CT segment text | Regex |
| 1st MDT: date | Meeting header (e.g. `Colorectal MDT 07/03/2025`) | Regex |
| 1st MDT: Treatment approach | MDT Outcome row | Regex + LLM fallback |

### P1 — High Value (present in most cases)
| Column | Source in Doc | Extraction Method |
|--------|--------------|-------------------|
| Demographics: Previous cancer | Clinical Details free text | LLM |
| Demographics: Previous cancer site | Clinical Details free text | LLM |
| Endoscopy: date | Clinical Details (`Flexi sig DATE:` or `Colonoscopy on DATE`) | Regex |
| Endoscopy: type | Clinical Details | Regex |
| Endoscopy: Findings | Clinical Details | Regex |
| Histology: Biopsy date | Inferred from endoscopy date if findings mention cancer | Derived |
| Baseline CT: Incidental findings Y/N | `incidental` keyword in CT segment | Regex |
| Baseline CT: Incidental detail | Text following `incidental` | Regex |
| MDT after 6 week: Decision | MDT Outcome row (if follow-up case) | LLM |
| AI Summary | All sections | LLM |

### P2 — Nice to Have (present in subset of cases)
| Column | Source in Doc | Extraction Method |
|--------|--------------|-------------------|
| Chemotherapy: drugs/cycles/dates | MDT Outcome / Clinical Details | LLM |
| Radiotherapy: dose/dates | MDT Outcome | LLM |
| Surgery: date/intent | MDT Outcome | LLM |
| 2nd MRI / 12-week MRI fields | Later MDT entries for same patient | LLM |
| Watch and Wait fields | MDT Outcome (`watch and wait` phrase) | LLM |
| CEA: date/value | Clinical Details | Regex + LLM |

> **Note**: Many P2 fields will be empty across most of the 50 cases.
> This is expected — the source documents are mostly first-presentation MDTs.
> Do not fabricate values. Leave blank with LOW confidence flag.

---

## 3. Confidence Scoring System

Every extracted field gets a confidence level. This is stored separately
from the value and displayed in the Streamlit UI and Excel output.

### Confidence Levels

| Level | Label | Colour (Excel) | Meaning |
|-------|-------|---------------|---------|
| `HIGH` | ✅ High | Green (`#C6EFCE`) | Extracted via deterministic regex from structured text |
| `MEDIUM` | ⚠️ Medium | Yellow (`#FFEB9C`) | Extracted via LLM from narrative text, plausible |
| `LOW` | ❌ Low | Red (`#FFC7CE`) | LLM inference with low certainty, or conflicting evidence |
| `INFERRED` | 🔵 Inferred | Blue (`#BDD7EE`) | Derived logically (e.g. biopsy date = colonoscopy date) |
| `MISSING` | ⬜ Missing | White (empty) | Not found in document — cell left blank |

### Confidence Assignment Rules

```
HIGH confidence when:
  - Regex matched against a labelled field (e.g. "NHS Number: 9990000001")
  - Date extracted with explicit "on [date]" phrasing
  - TNM notation matched exactly (e.g. "T3c, N1c, EMVI negative")
  - ICD10 code matched (e.g. "C18.6")
  - Gender from explicit Male/Female label

MEDIUM confidence when:
  - LLM extracted from free-text narrative
  - Treatment approach inferred from outcome text keywords
  - Previous cancer inferred from "history of..." phrasing
  - MDT decision extracted from multi-sentence outcome paragraph

LOW confidence when:
  - LLM returned a value but stated uncertainty
  - Multiple conflicting values found (e.g. CT says T2, MRI says T3)
  - Field partially matched (e.g. date found but no associated label)
  - LLM hallucination risk high (chemo drug names, doses)

INFERRED when:
  - Biopsy date inferred from colonoscopy date (per clinician Q4)
  - Initials derived from full name
  - M-stage inferred from "no metastases" / "liver lesion" phrases
```

---

## 4. Evidence Linking Format

Every extracted field stores a linked evidence object alongside the value.
This powers the **clickable evidence** feature in the UI.

### Per-field Evidence Object (JSON)

```json
{
  "field_name": "Baseline MRI: mrT(h)",
  "value": "T3c",
  "confidence": "HIGH",
  "evidence": {
    "source_section": "Clinical Details",
    "source_text": "MRI pelvis on 22/02/2024 T3c, N1c, EMVI negative, CRM clear",
    "extraction_method": "regex",
    "pattern_used": "mrT regex on MRI segment",
    "alternatives": [],
    "verified_by_agent": null
  }
}
```

### Field: `verified_by_agent`
After the extraction pipeline runs, the **validation agent** fills this field:
```json
"verified_by_agent": {
  "supported": true,
  "agent_evidence": "MRI pelvis on 22/02/2024 T3c...",
  "agent_confidence": 0.97,
  "flagged": false
}
```
If `supported: false` or `agent_confidence < 0.70`, the cell is flagged for clinician review
and overridden to `LOW` confidence regardless of original confidence level.

---

## 5. Clinician Question Resolutions

Based on `baseline-solution/reports/clinician-questions.md`:

### Q1: Multiple scan dates — which is primary?
**Decision**: Use the scan date most closely associated with the column being filled.
`Baseline MRI: date` uses the MRI date. `Baseline CT: date` uses the CT date.
The 1st MDT date uses the meeting header date. Do not mix modalities.

### Q2: Staging notation hierarchy
**Decision**: Prioritise `Integrated TNM Stage` field if populated.
If blank, use the inline staging text from Clinical Details (e.g. `T3 N0 M0`).
Always note which source was used in the evidence object (`source_section`).

### Q3: FOXTROT trial mapping
**Decision**: `FOXTROT` maps to `"downstaging chemotherapy"` in the treatment approach column.
Flag as `MEDIUM` confidence since it is a trial name, not a standard category label.

### Q4: Implicit biopsy dates
**Decision**: If colonoscopy findings mention cancer/carcinoma/biopsy and a date is present,
infer biopsy date = colonoscopy date. Mark as `INFERRED`. Do not infer if findings are
ambiguous or no cancer mention exists.

### Q5: MDT Decision extraction
**Decision**: If `"Outcome:"` label is present, extract text after it only.
If no label, extract the full MDT Outcome row text.
Do not truncate to one sentence — clinicians want the full plan.

### Q6: MRI vs CT staging conflict
**Decision**: MRI parameters go into MRI columns, CT parameters go into CT columns.
They are separate columns — do not merge or override one with the other.
If both conflict on the same field, note the conflict in the `alternatives` array
in the evidence object and flag `LOW` confidence.

---

## 6. Output Structure

### Excel Workbook — 3 Sheets

#### Sheet 1: `Patient Data`
- One row per patient (50 rows)
- Columns match `hackathon-database-prototype.xlsx` exactly (same names, same order)
- Cells colour-coded by confidence level
- Last column: `AI Summary` — 2-3 sentence plain English patient journey summary

#### Sheet 2: `Confidence Map`
- Same dimensions as Sheet 1
- Each cell contains the confidence label: `HIGH`, `MEDIUM`, `LOW`, `INFERRED`, or blank
- Allows clinicians to filter/sort by trust level

#### Sheet 3: `Validation Flags`
- Only rows/fields where `verified_by_agent = false` or `agent_confidence < 0.70`
- Columns: `Patient NHS Number`, `Field`, `Extracted Value`, `Agent Finding`, `Recommended Action`
- Acts as a **clinician review checklist** — nothing needs manual searching

---

## 7. Extraction Pipeline Flow

```
Word Doc (.docx)
      │
      ▼
[1] parse_docx.py
    - Segment into 50 cases
    - Store table row positions
    - Preserve source text per section
      │
      ▼
[2] extract_regex.py          (P0 fields — HIGH confidence)
    - Demographics, dates, TNM, MMR, MRI, CT
    - Returns: {field: value, evidence: {...}}
      │
      ▼
[3] extract_llm.py            (P1/P2 fields — MEDIUM/LOW confidence)
    - Gemini Flash 2.0
    - Previous cancer, treatment approach, chemo, surgery, watch+wait
    - Structured JSON output enforced via Gemini response_schema
    - Returns: {field: value, confidence: ..., evidence: {...}}
      │
      ▼
[4] merge.py
    - Combine regex + LLM outputs
    - Regex always wins if both extracted same field
    - Flag conflicts
      │
      ▼
[5] validation_agent.py       (reverse verification)
    - For each populated field, ask Gemini:
      "Is this value supported by the source document?"
    - Updates evidence.verified_by_agent
    - Downgrades confidence to LOW if unsupported
      │
      ▼
[6] write_excel.py
    - Sheet 1: Patient Data (colour-coded)
    - Sheet 2: Confidence Map
    - Sheet 3: Validation Flags
      │
      ▼
[7] streamlit_app.py
    - Upload Word doc
    - Show extraction progress
    - Interactive table with clickable evidence sidebar
    - Download Excel button
```

---

## 8. LLM Prompt Standards

All Gemini calls must follow these rules:

1. **Always use structured output** (`response_schema` with Gemini) — never parse free text from LLM
2. **Always include the source text** in the prompt — never ask LLM to recall from training data
3. **Always include a `"not_found"` option** in enum fields — never force the LLM to pick a value
4. **Always ask for evidence quote** — the exact phrase from source that supports the answer
5. **Temperature = 0** for all extraction calls — determinism over creativity

### Example Prompt Template

```python
PREVIOUS_CANCER_PROMPT = """
You are a clinical data extraction assistant. Extract information from the
clinical text below. Only use information explicitly present in the text.

CLINICAL TEXT:
{clinical_text}

CURRENT DIAGNOSIS (do NOT flag this as previous cancer):
{current_diagnosis}

TASK: Did this patient have a previous cancer before their current diagnosis?

Return JSON matching this schema:
{{
  "previous_cancer": "Yes" | "No" | "Unclear",
  "cancer_site": "<type of cancer or null>",
  "confidence": "high" | "medium" | "low",
  "evidence_quote": "<exact phrase from text that supports your answer or null>"
}}

If there is no mention of previous cancer, return "No" with null evidence_quote.
Do not infer or assume. Only return "Yes" if explicitly stated.
"""
```

---

## 9. What We Are NOT Doing

- ❌ Training or fine-tuning any model
- ❌ Storing patient data anywhere (process in memory only)
- ❌ Filling empty cells with LLM guesses (blank > wrong)
- ❌ Merging MRI and CT staging values
- ❌ Treating PET-CT as a CT scan
- ❌ Assuming follow-up fields exist if not in document

---

## 10. File Naming Conventions

```
solution/
├── parse_docx.py
├── extract_regex.py
├── extract_llm.py
├── merge.py
├── validation_agent.py
├── confidence.py
├── write_excel.py
├── pipeline.py          ← orchestrates all steps
├── app.py               ← Streamlit UI
├── prompts.py           ← all LLM prompts in one place
├── schema.py            ← field names, column order, confidence enums
└── tests/
    ├── test_regex.py
    ├── test_llm.py
    └── test_validation.py
```

---

*Last updated: 2026-03-16 | Author: Team Cloud9*
