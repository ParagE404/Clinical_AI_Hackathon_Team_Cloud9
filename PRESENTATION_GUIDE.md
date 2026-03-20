# Cloud9 MDT Extraction Pipeline - Technical Knowledge Guide
## For Teammates Presenting at the Hackathon

---

## 1. PROJECT OVERVIEW (What It Does)

**Problem:** NHS clinicians manually transcribe data from MDT (Multidisciplinary Team) meeting Word documents into Excel spreadsheets. This takes hours and is error-prone.

**Solution:** An AI pipeline that automatically extracts 88 clinical data fields from Word documents into a structured Excel database with full evidence tracing.

**Input:** `data/hackathon-mdt-outcome-proformas.docx` (50 patient cases)
**Output:** `output/generated-database-cloud9.xlsx` (structured database)

---

## 2. HOW TO RUN THE PROJECT

### Quick Start (Gemini - Working Version)
```bash
cd Clinical_AI_Hackathon_Team_Cloud9
source venv/bin/activate

# Set up Gemini API key in .env:
# LOCAL_LLM_PROVIDER=gemini
# GEMINI_API_KEY=your_key_here

python main.py                    # Full pipeline
python main.py --skip-validation  # Faster (no second pass)
streamlit run app.py              # Web UI
```

### Command Line Options
```bash
python main.py --workers 10          # More parallel workers
python main.py --cases 0-4           # Process only cases 0-4
python main.py --from-json           # Rebuild Excel without re-running LLM
```

---

## 3. ARCHITECTURE (6-Stage Pipeline)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        main.py (Orchestrator)                       │
└─────────────────────────────────────────────────────────────────────┘
                                   │
     ┌─────────────────────────────┼─────────────────────────────┐
     ▼                             ▼                             ▼
┌─────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ STAGE 1 │──▶│   STAGE 2   │──▶│   STAGE 3   │──▶│   STAGE 4   │
│parse_doc│   │ extract_llm │   │build_datafrm│   │write_excel  │
└─────────┘   └─────────────┘   └─────────────┘   └─────────────┘
     │              │                  │                 │
     ▼              ▼                  ▼                 ▼
  CaseText      CaseResult      3 DataFrames        Excel File
  (50 cases)    (88 fields      (data/evidence/     (2 sheets)
                 per case)       confidence)
                      │
                      ▼
              ┌─────────────┐   ┌─────────────┐
              │   STAGE 5   │──▶│   STAGE 6   │
              │  validate   │   │  fix_agent  │
              └─────────────┘   └─────────────┘
```

---

## 4. KEY FILES EXPLAINED

### `main.py` - The Orchestrator
**Lines 66-250:** Main entry point that runs all 6 stages in sequence.

**Key Points:**
- Parses command line arguments (`--cases`, `--workers`, `--skip-validation`)
- Calls each stage in order
- Saves intermediate results to `output/raw-extractions.json`

```python
# The main flow:
cases = parse_docx(DOCX_INPUT)           # Stage 1: Parse
extractions = extract_all_cases(cases)    # Stage 2: LLM Extract
data_df, evidence_df, conf_df = build_dataframes(extractions)  # Stage 3
write_styled_workbook(...)               # Stage 4: Write Excel
validations = validate_all(...)          # Stage 5: Validate
extractions = fix_all(...)               # Stage 6: Fix errors
```

---

### `parse_docx.py` - Document Parser
**What it does:** Reads the Word document and splits it into 50 patient cases.

**Key Data Structure:**
```python
@dataclass
class CaseText:
    case_index: int           # 0-49
    mdt_date_paragraph: str   # Meeting date header
    demographics_text: str    # Row 1: Patient details
    staging_text: str         # Row 3: Diagnosis/staging
    clinical_text: str        # Row 5: Imaging, endoscopy
    outcome_text: str         # Row 7: MDT decision
    full_text: str            # All rows with [ROW N]: markers
```

**Why Row Markers Matter:**
The full_text contains `[ROW 0]:`, `[ROW 1]:`, etc. markers. These help the LLM know WHERE in the document each piece of data came from, enabling evidence tracing.

---

### `schema.py` - Field Definitions (88 Columns)
**What it does:** Defines all 88 fields we need to extract.

**Key Data Structure:**
```python
class ColumnDef(NamedTuple):
    key: str             # e.g., "baseline_mri_mrT"
    header: str          # Exact Excel header (with typos preserved!)
    group: str           # e.g., "baseline_mri"
    extraction_hint: str # Instructions for the LLM
```

**Field Groups (important to explain):**

| Group | Fields | What It Contains |
|-------|--------|------------------|
| demographics | 7 | DOB, initials, MRN, NHS#, gender, previous cancer |
| endoscopy | 3 | Date, type, findings |
| histology | 3 | Biopsy result, date, MMR status |
| baseline_mri | 6 | MRI staging: T, N, EMVI, CRM, PSW |
| baseline_ct | 7 | CT staging and incidental findings |
| first_mdt | 2 | MDT date and treatment decision |
| chemotherapy | 5 | Chemo drugs, cycles, dates |
| etc... | 55 more | Follow-up MRI, surgery, watch & wait |

---

### `llm_client.py` - LLM Abstraction Layer
**What it does:** Allows switching between Ollama (local) and Gemini (cloud).

**How it works:**
```python
client = LLMClient()  # Reads from .env to pick provider

# Environment variables:
# LOCAL_LLM_PROVIDER=gemini  or  LOCAL_LLM_PROVIDER=ollama
# GEMINI_API_KEY=...         or  LOCAL_LLM_MODEL=llama3.1:8b

response = client.generate(
    prompt="Extract data from...",
    system_instruction="You are a clinical extractor...",
    json_mode=True  # Forces JSON output
)
```

**Why This Matters:**
- Gemini works well (~93% accuracy)
- Ollama 7B-9B models struggle with complex clinical extraction
- The architecture is ready for either - just change `.env`

---

### `extract_llm.py` - The Extraction Engine (CORE FILE)
**Lines 69-174:** The `SYSTEM_INSTRUCTION` - a massive prompt with 23 rules.

**Key Points to Explain:**

#### 1. Hybrid Extraction (Lines 241-293)
```python
# First: Regex extracts simple fields (MRN, NHS#, DOB)
pre_filled = regex_extract(case)

# Then: LLM extracts complex fields (staging, treatment decisions)
response = client.generate(prompt=prompt, ...)

# Merge: Regex results override LLM (more reliable)
merged = {**llm_fields, **pre_filled}
```

#### 2. Parallel Processing (Lines 302-374)
```python
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {pool.submit(extract_case, case, client): case ...}
```
This is why the pipeline is fast - processes 5 cases at once.

#### 3. Evidence Tracing
Every field returns:
```json
{
  "value": "3b",
  "evidence": "T3b, N1c, CRM clear",
  "confidence": "high"
}
```

**The 23 Rules (Important!):**
- **Rule 6-7:** Date format DD/MM/YYYY, convert 2-digit years
- **Rule 8-13:** TNM staging extraction (T3b → "3b", EMVI+ → "positive")
- **Rule 14a-f:** CRITICAL: Baseline vs follow-up imaging distinction
- **Rule 15-17:** Demographics (initials derivation, previous cancer logic)
- **Rule 18-21:** Endoscopy/histology classification
- **Rule 22-23:** Treatment approach mapping (CAPOX → "downstaging chemotherapy")

---

### `extract_regex.py` - Deterministic Pre-Extraction
**What it does:** Extracts simple structured fields without using the LLM.

**Fields extracted by regex:**
- MRN (Hospital Number): `Hospital Number: 12345`
- NHS Number: `NHS Number: 1234567890`
- DOB: `DOB: 26/05/1970`
- Gender: `Male` / `Female`
- Initials: Derived from patient name
- First MDT Date: From meeting header

**Why?** These fields are always in the same format, so regex is:
- 100% accurate
- Instant (no API call)
- Reduces token usage and hallucination risk

---

### `build_dataframe.py` - DataFrame Construction
**What it does:** Converts extraction results into 3 parallel DataFrames.

**The 3 DataFrames:**
1. `data_df` - The actual values (goes into Sheet 1)
2. `evidence_df` - The source quotes (goes into comments + Sheet 2)
3. `confidence_df` - HIGH/MEDIUM/LOW/NONE (shown in comments)

**Post-Processing Normalizations (Lines 77-108):**
```python
# Convert MRN/NHS to integers
data_df["MRN"] = pd.to_numeric(data_df["MRN"])

# Normalize CRM: "unsafe" → "threatened"
data_df["CRM"] = data_df["CRM"].apply(
    lambda v: "threatened" if v == "unsafe" else v
)

# Normalize endoscopy type
# "colonoscopy" → "Colonoscopy complete"
# "flexible sigmoidoscopy" → "flexi sig"
```

---

### `write_excel.py` - Excel Output
**What it does:** Creates the final Excel file with styling and evidence.

**Output has 2 sheets:**
1. **Sheet 1 (Patient Data):** Values with hover comments
   - Each cell has a comment: `[Confidence: HIGH]` + source quote
2. **Sheet 2 (Evidence Map):** Full audit trail
   - Shows `[confidence] verbatim evidence` in every cell

**Styling:**
- Copies fonts, colors, borders from the prototype template
- Ensures output matches NHS expected format

---

### `validate_agent.py` - Quality Assurance
**What it does:** Second LLM pass to catch errors.

**Checks for:**

| Issue Type | Description |
|------------|-------------|
| `hallucination` | Extracted value has no evidence in source |
| `misquote` | Evidence doesn't match source text |
| `incorrect_value` | Value doesn't match the evidence |
| `missing_data` | Data exists in source but wasn't extracted |

**Fix Agent (Lines 278-466):**
When issues are found, a second LLM call re-extracts ONLY the flagged fields with the validation feedback. This is like giving the LLM a "second chance" with hints about what went wrong.

---

### `app.py` - Streamlit Web UI
**Run with:** `streamlit run app.py`

**3 Pages:**
1. **Run Pipeline:** Upload DOCX, select cases, run extraction, download Excel
2. **Browse Results:** View extracted data per case with evidence
3. **Validation Report:** Run validation agent, see issues by severity

---

## 5. DATA FLOW EXAMPLE

**Input (from Word document):**
```
[ROW 1]: Hospital Number: 12345 | NHS Number: 9876543210 | Name: JOHN SMITH | Gender: Male | DOB: 15/03/1965
[ROW 5]: CT TAP 10/01/2025: No metastases. MRI pelvis 12/01/25: T3b, N1c, EMVI positive, CRM clear
[ROW 7]: Outcome: For neoadjuvant CRT then surgery
```

**After Stage 2 (extract_llm.py):**
```json
{
  "mrn": {"value": "12345", "evidence": "Hospital Number: 12345", "confidence": "high"},
  "baseline_mri_mrT": {"value": "3b", "evidence": "T3b, N1c, EMVI positive, CRM clear", "confidence": "high"},
  "baseline_ct_M": {"value": "0", "evidence": "No metastases", "confidence": "medium"},
  "first_mdt_treatment_approach": {"value": "downstaging nCRT", "evidence": "For neoadjuvant CRT", "confidence": "high"}
}
```

**After Stage 4 (Excel output):**
- Cell A2 shows: `12345` with hover comment: `[Confidence: HIGH] Hospital Number: 12345`
- Cell N2 shows: `3b` with hover comment: `[Confidence: HIGH] T3b, N1c, EMVI positive, CRM clear`

---

## 6. KEY TECHNICAL DECISIONS TO EXPLAIN

### Why Hybrid Regex + LLM?
- Regex handles structured fields (MRN, dates) with 100% accuracy
- LLM handles complex clinical interpretation (staging, treatment decisions)
- Reduces API costs and hallucination risk

### Why Parallel Processing?
- 5 workers = 5 cases processed simultaneously
- 50 cases: ~15 min sequential → ~2 min parallel (8x speedup)

### Why Evidence Tracing?
- Clinical data MUST be auditable
- Clinicians can hover any cell to see WHERE the value came from
- Builds trust in AI-generated data

### Why Validation Agent?
- LLMs can hallucinate or misinterpret
- Second pass catches 5-10% of errors
- Fix agent corrects them automatically

---

## 7. LIMITATIONS TO ACKNOWLEDGE

1. **Local LLM Performance Gap:**
   - Gemini API: ~93% accuracy (works great)
   - Ollama 7B-9B: ~70-80% accuracy (struggles with complex clinical extraction)
   - Hardware limits prevent running larger local models

2. **Single Document Format:**
   - Built for this specific MDT proforma template
   - Other hospitals may use different formats

3. **Not 100% Accurate:**
   - ~7% of fields may need manual review
   - Complex multi-value fields are harder to extract

### Future Solution: Self-Hosted Private Cloud
- Deploy 14B+ parameter model on NHS/Trust-owned infrastructure
- Own cloud = No third-party data sharing = Full GDPR/NHS IG compliance
- Best of both worlds: High accuracy + Data privacy preserved

---

## 8. DEMO SCRIPT

**Suggested Demo Flow:**

1. **Show the input DOCX** (open in Word, show messy tables)
2. **Run Streamlit app:** `streamlit run app.py`
3. **Upload the DOCX** and start extraction
4. **Show real-time progress** (parallel workers)
5. **Download and open Excel**
6. **Key demo moments:**
   - Hover over a cell to show evidence comment
   - Show Sheet 2 (Evidence Map) for full audit trail
   - Show a staging value (T3b) and its source evidence
7. **Run validation** and show the report
8. **Show before/after** (50 cases manually = hours, pipeline = 2 minutes)

---

## 9. Q&A PREPARATION

**Q: How accurate is it?**
A: 93.2% on our ground truth test case. The validation agent catches most remaining errors.

**Q: Is it hackathon compliant (100% local)?**
A: The architecture supports both local Ollama and cloud Gemini. Currently demonstrating with Gemini due to local model accuracy limitations. For production, we'd deploy a larger model on NHS-owned private cloud infrastructure.

**Q: Can it handle different MDT formats?**
A: Would need to adjust the regex patterns and prompt rules. The architecture is modular.

**Q: What if the LLM hallucinates?**
A: Every value has evidence tracing. The validation agent flags hallucinations. Empty is always better than wrong.

**Q: How does it handle ambiguous data?**
A: The prompt has 23 specific rules. When truly ambiguous, it leaves the field blank with confidence="none".

**Q: Why not use a larger local model?**
A: Hardware constraints (MacBook RAM/VRAM). Models >8B parameters don't run efficiently. The solution would be to self-host on GPU-enabled infrastructure.

---

## 10. FILE STRUCTURE QUICK REFERENCE

```
Clinical_AI_Hackathon_Team_Cloud9/
├── main.py               # Pipeline orchestrator (CLI entry point)
├── app.py                # Streamlit web UI
├── parse_docx.py         # DOCX parser → CaseText objects
├── schema.py             # 88 column definitions
├── llm_client.py         # Ollama/Gemini abstraction
├── extract_llm.py        # LLM extraction with 23 rules
├── extract_regex.py      # Deterministic regex pre-extraction
├── build_dataframe.py    # DataFrame construction + normalization
├── write_excel.py        # Styled Excel writer
├── validate_agent.py     # Validation + Fix agents
├── .env                  # API keys and config
├── data/
│   ├── hackathon-mdt-outcome-proformas.docx   # Input
│   └── hackathon-database-prototype.xlsx       # Template
└── output/
    ├── generated-database-cloud9.xlsx   # Final output
    ├── raw-extractions.json             # Raw LLM results
    └── validation-report.json           # Validation results
```

---

**Good luck with the presentation!**
