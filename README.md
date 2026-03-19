# Cloud9 MDT Extraction Pipeline

**🏥 AI-powered clinical data extraction using local LLMs (hackathon compliant)**

An AI-powered pipeline that automatically extracts structured clinical data from colorectal cancer MDT (Multidisciplinary Team) meeting proformas (Word documents) into a searchable Excel database.

Built for the **Clinical AI Hackathon** — solving the problem of manually transcribing MDT outcomes into longitudinal spreadsheets, a process that currently takes clinicians hours of copy-paste work per patient.

## 🎯 Hackathon Compliance

✅ **Zero cloud API calls** — Uses [Ollama](https://ollama.ai) for 100% local LLM inference
✅ **Model size ≤5GB** — llama3.1:8b (4.7GB), mistral:7b (4.1GB), or qwen2.5:7b (4.5GB)
✅ **On-device execution** — Runs entirely on MacBook M4
✅ **Reproducible results** — Deterministic outputs with temperature=0.0

See **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** for full setup instructions.

## Problem

NHS colorectal cancer MDT meetings generate Word-based proformas for each patient discussion. These contain demographics, staging, imaging results, endoscopy findings, histology, and treatment decisions — all in semi-structured tables and free text. Clinicians need this data in a structured Excel database for auditing, outcome tracking, and research, but manual extraction is tedious and error-prone.

**Input:** `data/hackathon-mdt-outcome-proformas.docx` — 50 synthetic patient cases across MDT meeting proformas.

**Output:** A structured Excel workbook matching the 88-column schema in `data/hackathon-database-prototype.xlsx`, with full evidence tracing for every extracted value.

## Results

| Metric | Value |
|---|---|
| Cases processed | 50 / 50 |
| Columns in schema | 88 |
| Cells populated | 786 / 4,400 (17.9%) |
| Improvement over baseline | +111 cells (+16.4%) |
| Case 0 accuracy vs ground truth | 93.2% (82/88 match) |
| Extraction errors | 0 |

The 50 unpopulated columns are downstream longitudinal fields (surgery dates, chemotherapy cycles, watch-and-wait tracking) that are not present in the initial MDT discussion documents.

### Performance

With parallelisation enabled (default: 5 workers), the pipeline achieves significant speedup:

| Metric | Sequential (Before) | Parallel (After, 5 workers) | Speedup |
|---|---|---|---|
| Extraction (50 cases) | ~5 min | ~15-20 s | **15-20x** |
| Validation (50 cases) | ~5 min | ~15-20 s | **15-20x** |
| Fix pass (50 cases) | ~5 min | ~15-20 s | **15-20x** |
| **End-to-end (full pipeline)** | **~15 min** | **< 2 min** | **~8x** |

Performance scales linearly with the number of workers (configurable via `--workers` flag), up to API rate limits.

## Architecture

The pipeline runs in 6 sequential stages:

```
DOCX Input
    |
    v
[Stage 1] parse_docx.py     -- Deterministic DOCX parser, extracts 50 case tables
    |                           with row-level markers ([ROW 0] - [ROW 7])
    v
[Stage 2] extract_llm.py    -- Local LLM extraction (Ollama) with 23 clinical rules
    |                           Returns {value, evidence, confidence} per field
    v
[Stage 3] build_dataframe.py -- Builds 3 parallel DataFrames (data, evidence, confidence)
    |                            Applies post-processing normalizations
    v
[Stage 4] write_excel.py    -- Writes styled Excel from prototype template
    |                           Sheet 1: Data + hover comments with evidence
    |                           Sheet 2: Evidence Map (full audit trail)
    v
[Stage 5] validate_agent.py -- (Optional) Second LLM pass to cross-check
    |                           extractions against source text
    v
[Stage 6] validate_agent.py -- (Optional) Fix agent that re-extracts flagged fields
                                using validation feedback, then rebuilds the Excel
```

## Project Structure

```
cloud9-solution/
├── main.py               # Pipeline orchestrator (CLI entry point)
├── app.py                # Streamlit web UI (upload, run, browse, validate)
├── llm_client.py         # 🆕 LLM abstraction layer (Ollama/Gemini support)
├── verify_ollama_setup.py # 🆕 Setup verification script
├── parse_docx.py         # DOCX parser — segments proformas into CaseText objects
├── schema.py             # Single source of truth: 88 column definitions with LLM hints
├── extract_llm.py        # LLM-powered extraction with evidence tracing
├── build_dataframe.py    # DataFrame construction + post-processing normalizations
├── write_excel.py        # Styled Excel writer with evidence comments
├── validate_agent.py     # AI validation agent + fix agent for cross-checking/correcting
├── requirements.txt      # Python dependencies
├── .env                  # Environment config (not committed)
├── .env.example          # 🆕 Template for .env with Ollama settings
├── MIGRATION_GUIDE.md    # 🆕 Full local LLM setup guide
├── data/
│   ├── hackathon-mdt-outcome-proformas.docx   # Input DOCX with 50 cases
│   └── hackathon-database-prototype.xlsx       # Prototype Excel template
├── issues/               # GitHub issue descriptions for team tasks
└── output/
    ├── generated-database-cloud9.xlsx   # Final output workbook
    ├── raw-extractions.json             # Raw LLM results (50 cases, all fields)
    └── validation-report.json           # Validation agent results
```

## Module Details

### `parse_docx.py` — Document Parser
- Walks DOCX XML body elements to maintain paragraph/table interleaving
- Identifies MDT proforma tables by "Patient Details" header
- Extracts text per table row with `[ROW N]:` markers for evidence tracing
- Captures MDT meeting date from paragraph preceding each table
- Output: `list[CaseText]` — one per patient, with `full_text`, `demographics_text`, `staging_text`, `clinical_text`, `outcome_text`

### `schema.py` — Column Definitions
- Defines all 88 columns as `ColumnDef(key, header, group, extraction_hint)`
- Headers are character-for-character copies from the prototype Excel (preserving newlines and typos)
- Extraction hints provide clinical context and rules for each field (e.g., where to look in the document, how to interpret staging shorthand)
- Provides derived lookups: `KEY_TO_HEADER`, `HEADER_TO_KEY`, `FIELD_GROUPS`

### `llm_client.py` — LLM Abstraction Layer (NEW)
- Unified interface for local (Ollama) and cloud (Gemini) LLM providers
- Automatically selects provider based on environment variables
- OpenAI-compatible API for Ollama (seamless integration)
- JSON mode support for structured output
- Token usage tracking

### `extract_llm.py` — LLM Extraction Engine
- Uses local LLM via Ollama (hackathon compliant) or Gemini (testing only)
- **Parallel processing:** Uses `ThreadPoolExecutor` to process multiple cases simultaneously (default: 5 workers, configurable via `--workers`)
- Comprehensive 23-rule system instruction covering:
  - Date format conversion (2-digit years, zero-padding)
  - TNM staging extraction (T/N values, EMVI/CRM/PSW normalization, dash notation)
  - Demographics rules (initials generation, previous cancer logic)
  - Endoscopy/histology classification
  - Treatment approach mapping (7 categories + investigation-only exclusion)
- Every extracted field returns `{value, evidence, confidence}` — the evidence must be a verbatim substring from the source
- Retry logic with exponential backoff (1s, 2s) for transient API errors

### `build_dataframe.py` — DataFrame Builder
- Converts `list[CaseResult]` into three parallel 50x88 DataFrames: data, evidence, confidence
- Pre-processing: infers `endoscopy_type` from LLM evidence when the value was left blank but colonoscopy/flexi sig evidence exists
- Post-processing normalizations:
  - MRN/NHS number to numeric
  - DOB to datetime
  - Endoscopy type normalization (`"colonoscopy"` → `"Colonoscopy complete"`, `"flexible sigmoidoscopy"` → `"flexi sig"`)
  - CRM normalization (`"unsafe"` → `"threatened"`)
- Sorts rows by NHS number for consistent output ordering

### `write_excel.py` — Excel Writer
- Clones styling (fonts, fills, borders, alignment, number formats) from the prototype workbook template
- **Sheet 1 (Patient Data):** Extracted values with cell comments — hover any cell to see `[Confidence: HIGH/MEDIUM/LOW]` and the verbatim source evidence quote
- **Sheet 2 (Evidence Map):** Full audit trail with `[confidence] evidence quote` in every cell

### `validate_agent.py` — Validation Agent
- Optional second LLM pass that cross-checks every populated cell against the original document
- **Parallel processing:** Uses `ThreadPoolExecutor` to validate multiple cases simultaneously
- Checks: evidence actually appears verbatim in source, value correctly derived from evidence, no important data missed
- Outputs a JSON report with issue types: `hallucination`, `misquote`, `incorrect_value`, `missing_data`
- Each issue classified by severity: `critical`, `warning`, `info`
- **Fix agent:** Re-extracts flagged fields using validation feedback with parallel processing

## Setup

### Prerequisites
- **Python 3.9+**
- **MacBook M4** (or any system capable of running Ollama)
- **16GB+ RAM** (recommended for llama3.1:8b)

### Quick Start (Local LLM - Hackathon Compliant)

```bash
# 1. Install Ollama
brew install ollama

# 2. Start Ollama service
ollama serve &

# 3. Pull a local LLM model (≤5GB)
ollama pull llama3.1:8b  # 4.7GB - RECOMMENDED

# 4. Clone repository and install dependencies
cd Clinical_AI_Hackathon_Team_Cloud9
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Edit .env to set:
#   LOCAL_LLM_PROVIDER=ollama
#   LOCAL_LLM_MODEL=llama3.1:8b

# 6. Verify setup
python verify_ollama_setup.py

# 7. Run pipeline
python main.py
```

**📖 Full setup guide:** See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for detailed instructions, troubleshooting, and model comparisons.

### Environment Variables

**For Local LLM (Ollama - Hackathon Compliant):**

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOCAL_LLM_PROVIDER` | Yes | `ollama` | LLM provider (`ollama` or `gemini`) |
| `LOCAL_LLM_MODEL` | Yes | `llama3.1:8b` | Ollama model name |
| `LOCAL_LLM_BASE_URL` | No | `http://localhost:11434/v1` | Ollama API endpoint |
| `LOCAL_LLM_TEMPERATURE` | No | `0.0` | Generation temperature (deterministic) |

**For Cloud LLM (Gemini - Testing Only, NOT Hackathon Compliant):**

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOCAL_LLM_PROVIDER` | Yes | — | Set to `gemini` |
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model to use |

## Usage

All commands should be run from the project root with the venv activated:

```bash
source venv/bin/activate
```

### Web UI (Streamlit)

The easiest way to run the pipeline is via the Streamlit app:

```bash
streamlit run app.py
```

The app has three pages accessible from the sidebar:

| Page | Description |
|---|---|
| **Run Pipeline** | Upload a DOCX, choose case range, run extraction, download the Excel output |
| **Browse Results** | Explore extracted values per case with evidence and confidence filters |
| **Validation Report** | Run the AI validation agent and view critical/warning/info issues per field |

**Important:** Select **"ollama"** as LLM Provider in the sidebar for hackathon compliance. The UI will show a warning if you select "gemini" (cloud-based, testing only).

---

### CLI

### Full pipeline (50 cases + validation)
```bash
python main.py
```

### Use more parallel workers for faster processing
```bash
python main.py --workers 10
```
Default is 5 workers. Increase for faster processing if your API quota allows.

### Skip validation (faster, no second API pass)
```bash
python main.py --skip-validation
```

### Process specific cases only
```bash
# Range of cases
python main.py --cases 0-4 --skip-validation

# Specific cases
python main.py --cases 0,5,10 --skip-validation
```

### Rebuild Excel from existing extractions (no API calls)
```bash
python main.py --from-json --skip-validation
```
This reloads `output/raw-extractions.json` and rebuilds the Excel workbook with all post-processing normalizations. Useful for iterating on post-processing without re-running the LLM.

## Output Files

| File | Description |
|---|---|
| `output/generated-database-cloud9.xlsx` | Final structured database (Sheet 1: data with evidence comments, Sheet 2: evidence map) |
| `output/raw-extractions.json` | Raw LLM extraction results — 50 cases, 88 fields each, with value/evidence/confidence |
| `output/validation-report.json` | Validation agent results (only when validation is run) |

## Evidence Tracing

Every cell in the output is traceable back to the source document:

1. **Hover comments (Sheet 1):** Each populated cell has a comment showing the confidence level and the verbatim source quote the LLM used to extract the value.

2. **Evidence Map (Sheet 2):** A parallel sheet with the evidence quote and confidence level in every cell, providing a complete audit trail.

3. **Raw JSON (raw-extractions.json):** The full extraction output with all field-level metadata, useful for downstream analysis or debugging.

## Clinical Field Groups

The 88 columns are organized into these groups:

| Group | Columns | Description |
|---|---|---|
| Demographics | 7 | DOB, initials, MRN, NHS number, gender, previous cancer |
| Endoscopy | 3 | Date, type (colonoscopy/flexi sig), findings |
| Histology | 3 | Biopsy result, date, MMR status |
| Baseline MRI | 6 | Date, mrT, mrN, mrEMVI, mrCRM, mrPSW |
| Baseline CT | 7 | Date, T, N, EMVI, M, incidental findings |
| 1st MDT | 2 | Date, treatment approach |
| Chemotherapy | 5 | Goals, drugs, cycles, dates, breaks |
| Immunotherapy | 2 | Dates, regimen |
| Radiotherapy | 4 | Dose, boost, dates, concomitant chemo |
| CEA / DRE | 4 | CEA date/value, DRE date/finding |
| Surgery | 3 | Defunctioned, date, intent |
| 2nd MRI | 8 | Date, pathway status, staging, TRG score |
| MDT follow-ups | 4 | 6-week and 12-week MDT dates/decisions |
| 12-week MRI | 7 | Date, staging, TRG score |
| Flex sig follow-up | 2 | Date, findings |
| Watch and wait | 6 | Entry date, intent, frequency, progression, death |
| W&W tracking | 15 | Longitudinal flexi/MRI dates and due dates |

## Team

**Team Cloud9** — Clinical AI Hackathon
