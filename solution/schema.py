"""
schema.py — Single source of truth for all field names, column order,
confidence levels, and Excel formatting constants.

Every other module imports from here. Never hardcode column names elsewhere.
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Confidence Levels
# ---------------------------------------------------------------------------

class Confidence(str, Enum):
    HIGH      = "HIGH"      # Regex on structured/labelled text
    MEDIUM    = "MEDIUM"    # LLM from narrative text
    LOW       = "LOW"       # LLM with uncertainty or conflict
    INFERRED  = "INFERRED"  # Logically derived (e.g. biopsy date = colonoscopy date)
    MISSING   = "MISSING"   # Not found in document — cell left blank


# Excel fill colours per confidence level (openpyxl hex, no leading #)
CONFIDENCE_COLOURS = {
    Confidence.HIGH:     "C6EFCE",  # Green
    Confidence.MEDIUM:   "FFEB9C",  # Yellow
    Confidence.LOW:      "FFC7CE",  # Red
    Confidence.INFERRED: "BDD7EE",  # Blue
    Confidence.MISSING:  "FFFFFF",  # White (no fill)
}


# ---------------------------------------------------------------------------
# Extraction Methods
# ---------------------------------------------------------------------------

class ExtractionMethod(str, Enum):
    REGEX   = "regex"
    LLM     = "llm"
    DERIVED = "derived"   # Computed from other extracted fields


# ---------------------------------------------------------------------------
# Column Definitions
# ---------------------------------------------------------------------------
# Each entry is a dict with:
#   key          : internal Python key used throughout the pipeline
#   excel_header : exact column header matching the prototype spreadsheet
#   priority     : P0 | P1 | P2
#   method       : primary extraction method
#   source       : which doc section to search
#   notes        : any special handling

COLUMNS = [
    # --- DEMOGRAPHICS ---
    {
        "key":          "dob",
        "excel_header": "Demographics: \nDOB(a)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Patient Details table row 2",
        "notes":        "Format DD/MM/YYYY",
    },
    {
        "key":          "initials",
        "excel_header": "Demographics: Initials(b)",
        "priority":     "P0",
        "method":       ExtractionMethod.DERIVED,
        "source":       "Derived from full name",
        "notes":        "First letter of first name + first letter of last name",
    },
    {
        "key":          "mrn",
        "excel_header": "Demographics: MRN(c)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Hospital Number label in Patient Details",
        "notes":        "",
    },
    {
        "key":          "nhs_number",
        "excel_header": "Demographics: \nNHS number(d)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "NHS Number label in Patient Details",
        "notes":        "Starts with NNN (synthetic) or 999... (anonymised)",
    },
    {
        "key":          "gender",
        "excel_header": "Demographics: \nGender(e)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Male/Female in Patient Details table",
        "notes":        "Normalise to title case: Male / Female",
    },
    {
        "key":          "previous_cancer",
        "excel_header": "Demographics:\nPrevious cancer \n(y, n) \nif yes, where(f)",
        "priority":     "P1",
        "method":       ExtractionMethod.LLM,
        "source":       "Clinical Details free text",
        "notes":        "Do NOT flag current colorectal diagnosis. Return Yes/No/Unclear.",
    },
    {
        "key":          "previous_cancer_site",
        "excel_header": "Demographics: \nState site of previous cancer(f)",
        "priority":     "P1",
        "method":       ExtractionMethod.LLM,
        "source":       "Clinical Details free text",
        "notes":        "Only populate if previous_cancer = Yes. Return N/A otherwise.",
    },

    # --- ENDOSCOPY ---
    {
        "key":          "endoscopy_date",
        "excel_header": "Endoscopy: date(f)",
        "priority":     "P1",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details — colonoscopy/flexi sig mention",
        "notes":        "Handles: TYPE DATE: findings | TYPE on DATE: findings",
    },
    {
        "key":          "endoscopy_type",
        "excel_header": "Endosopy type: flexi sig, incomplete colonoscopy, colonoscopy complete - if gets to ileocecal valve(f) ",
        "priority":     "P1",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details",
        "notes":        "Normalise to: flexi sig | incomplete colonoscopy | Colonoscopy complete",
    },
    {
        "key":          "endoscopy_findings",
        "excel_header": "Endoscopy: Findings(f)",
        "priority":     "P1",
        "method":       ExtractionMethod.REGEX,
        "source":       "Text following endoscopy type/date",
        "notes":        "",
    },

    # --- HISTOLOGY ---
    {
        "key":          "biopsy_result",
        "excel_header": "Histology: Biopsy result(g)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Diagnosis field in Staging/Diagnosis table row",
        "notes":        "Fallback: search outcome text for adenocarcinoma/carcinoma/adenoma",
    },
    {
        "key":          "biopsy_date",
        "excel_header": "Histology: Biopsy date(g)",
        "priority":     "P1",
        "method":       ExtractionMethod.DERIVED,
        "source":       "Inferred from endoscopy date",
        "notes":        "INFERRED confidence. Only set if endoscopy findings mention cancer/biopsy.",
    },
    {
        "key":          "mmr_status",
        "excel_header": "Histology: \nMMR status(g/h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Anywhere in document",
        "notes":        "Normalise to: Deficient | Proficient | blank",
    },

    # --- BASELINE MRI ---
    {
        "key":          "baseline_mri_date",
        "excel_header": "Baseline MRI: date(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details MRI segment",
        "notes":        "Matches: MRI pelvis | MRI rectum | MRI liver | MRI on DATE",
    },
    {
        "key":          "baseline_mri_mrT",
        "excel_header": "Baseline MRI: mrT(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "MRI segment text",
        "notes":        "e.g. T3c, T1 sm1, T2. Prefix mr/c/p optional.",
    },
    {
        "key":          "baseline_mri_mrN",
        "excel_header": "Baseline MRI: mrN(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "MRI segment text",
        "notes":        "e.g. N0, N1c, N1a",
    },
    {
        "key":          "baseline_mri_mrEMVI",
        "excel_header": "Baseline MRI: mrEMVI(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "MRI segment text",
        "notes":        "Normalise to: positive | negative",
    },
    {
        "key":          "baseline_mri_mrCRM",
        "excel_header": "Baseline MRI: mrCRM(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "MRI segment text",
        "notes":        "Normalise to: clear | involved | threatened | unsafe",
    },
    {
        "key":          "baseline_mri_mrPSW",
        "excel_header": "Baseline MRI: mrPSW(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "MRI segment text",
        "notes":        "Normalise to: clear | unsafe | positive | negative",
    },

    # --- BASELINE CT ---
    {
        "key":          "baseline_ct_date",
        "excel_header": "Baseline CT: Date(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details CT segment",
        "notes":        "Matches CT TAP | CT abdomen | CT pelvis | CT colonography. Exclude PET-CT.",
    },
    {
        "key":          "baseline_ct_T",
        "excel_header": "Baseline CT: T(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "CT segment text",
        "notes":        "",
    },
    {
        "key":          "baseline_ct_N",
        "excel_header": "Baseline CT: N(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "CT segment text",
        "notes":        "",
    },
    {
        "key":          "baseline_ct_EMVI",
        "excel_header": "Baseline CT: EMVI(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "CT segment text",
        "notes":        "Normalise to: positive | negative",
    },
    {
        "key":          "baseline_ct_M",
        "excel_header": "Baseline CT: M(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "CT segment text",
        "notes":        "Infer M0 from 'no metastases'. Infer M1 from 'metastases/liver lesion'. Else extract directly.",
    },
    {
        "key":          "baseline_ct_incidental_yn",
        "excel_header": "Baseline CT: Incidental findings requiring follow up? Y/N(h)",
        "priority":     "P1",
        "method":       ExtractionMethod.REGEX,
        "source":       "CT segment — 'incidental' keyword",
        "notes":        "Return Y or N only",
    },
    {
        "key":          "baseline_ct_incidental_detail",
        "excel_header": "Baseline CT: Detail incidental finding(h)",
        "priority":     "P1",
        "method":       ExtractionMethod.REGEX,
        "source":       "CT segment — text following 'incidental'",
        "notes":        "",
    },

    # --- 1ST MDT ---
    {
        "key":          "first_mdt_date",
        "excel_header": "1st MDT: date(i)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "Meeting header: 'Colorectal Multidisciplinary Meeting DD/MM/YYYY'",
        "notes":        "",
    },
    {
        "key":          "first_mdt_treatment_approach",
        "excel_header": "1st MDT: Treatment approach \n(TNT, downstaging chemotherapy, downstaging nCRT, downstaging shortcourse RT, Papillon +/- EBRT, straight to surgery(h)",
        "priority":     "P0",
        "method":       ExtractionMethod.REGEX,
        "source":       "MDT Outcome row",
        "notes":        "See TREATMENT_APPROACH_MAP below for keyword mappings.",
    },

    # --- CHEMOTHERAPY ---
    {
        "key":          "chemo_goal",
        "excel_header": "Chemotherapy: Treatment goals  (curative, palliative)",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome / Clinical Details",
        "notes":        "Return: curative | palliative | blank",
    },
    {
        "key":          "chemo_drugs",
        "excel_header": "Chemotherapy: Drugs",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome / Clinical Details",
        "notes":        "LOW confidence — high hallucination risk for drug names",
    },
    {
        "key":          "chemo_cycles",
        "excel_header": "Chemotherapy: Cycles",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "chemo_dates",
        "excel_header": "Chemotherapy: Dates",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "chemo_breaks",
        "excel_header": "Chemotherapy: Breaks",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },

    # --- IMMUNOTHERAPY ---
    {
        "key":          "immunotherapy_dates",
        "excel_header": "Immunotherapy: Dates",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "immunotherapy",
        "excel_header": "Immunotherapy",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },

    # --- RADIOTHERAPY ---
    {
        "key":          "rt_total_dose",
        "excel_header": "Radiotheapy: Total dose",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "rt_boost",
        "excel_header": "Radiotheapy: Boost",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "rt_dates",
        "excel_header": "Radiotherapy: Dates",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "rt_concomitant_chemo",
        "excel_header": "Radiotheapy: Concomittant chemotherapy ",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },

    # --- CEA ---
    {
        "key":          "cea_date",
        "excel_header": "CEA: Date",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details",
        "notes":        "CEA followed by date",
    },
    {
        "key":          "cea_value",
        "excel_header": "CEA: Value",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details",
        "notes":        "",
    },
    {
        "key":          "cea_dre_date",
        "excel_header": "CEA: DRE date ",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Clinical Details",
        "notes":        "",
    },
    {
        "key":          "cea_dre_finding",
        "excel_header": "CEA: DRE finding",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "Clinical Details",
        "notes":        "",
    },

    # --- SURGERY ---
    {
        "key":          "surgery_defunctioned",
        "excel_header": "Surgery: Defunctioned?",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "Return Y | N | blank",
    },
    {
        "key":          "surgery_date",
        "excel_header": "Surgery: Date of surgery ",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "surgery_intent",
        "excel_header": "Surgery: Intent, pre-neoadjuvant therapy",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },

    # --- 2ND MRI ---
    {
        "key":          "second_mri_date",
        "excel_header": "2nd MRI: Date",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Later MDT entry for same patient",
        "notes":        "Only present in multi-visit patients",
    },
    {
        "key":          "second_mri_pathway_status",
        "excel_header": "2nd MRI: Patient pathway status",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "Clinical Details of follow-up MDT",
        "notes":        "",
    },
    {
        "key":          "second_mri_mrT",
        "excel_header": "2nd MRI: mrT",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "2nd MRI segment",
        "notes":        "",
    },
    {
        "key":          "second_mri_mrN",
        "excel_header": "2nd MRI: mrN",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "2nd MRI segment",
        "notes":        "",
    },
    {
        "key":          "second_mri_mrEMVI",
        "excel_header": "2nd MRI: mrEMVI",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "2nd MRI segment",
        "notes":        "Normalise to: positive | negative",
    },
    {
        "key":          "second_mri_mrCRM",
        "excel_header": "2nd MRI: mrCRM",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "2nd MRI segment",
        "notes":        "Normalise to: clear | involved | threatened",
    },
    {
        "key":          "second_mri_mrPSW",
        "excel_header": "2nd MRI: mrPSW",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "2nd MRI segment",
        "notes":        "",
    },
    {
        "key":          "second_mri_trg",
        "excel_header": "2nd MRI: mrTRG score ",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "2nd MRI segment",
        "notes":        "TRG 1-5 scale",
    },

    # --- MDT AFTER 6 WEEKS ---
    {
        "key":          "mdt_6wk_date",
        "excel_header": "MDT (after 6 week: Date",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Follow-up MDT meeting header",
        "notes":        "",
    },
    {
        "key":          "mdt_6wk_decision",
        "excel_header": "MDT (after 6 week: Decision ",
        "priority":     "P1",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome row of follow-up entry",
        "notes":        "If 'Outcome:' label present, extract text after it only.",
    },

    # --- 12-WEEK MRI ---
    {
        "key":          "mri_12wk_date",
        "excel_header": "12 week MRI: Date",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week follow-up MDT entry",
        "notes":        "",
    },
    {
        "key":          "mri_12wk_mrT",
        "excel_header": "12 week MRI: mrT",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week MRI segment",
        "notes":        "",
    },
    {
        "key":          "mri_12wk_mrN",
        "excel_header": "12 week MRI: mrN",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week MRI segment",
        "notes":        "",
    },
    {
        "key":          "mri_12wk_mrEMVI",
        "excel_header": "12 week MRI: mrEMVI",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week MRI segment",
        "notes":        "",
    },
    {
        "key":          "mri_12wk_mrCRM",
        "excel_header": "12 week MRI: mrCRM",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week MRI segment",
        "notes":        "",
    },
    {
        "key":          "mri_12wk_mrPSW",
        "excel_header": "12 week MRI: mrPSW",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week MRI segment",
        "notes":        "",
    },
    {
        "key":          "mri_12wk_trg",
        "excel_header": "12 week MRI: mrTRG score ",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "12-week MRI segment",
        "notes":        "",
    },

    # --- FLEX SIG ---
    {
        "key":          "flex_sig_date",
        "excel_header": "Flex sig: Date",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Follow-up Clinical Details",
        "notes":        "",
    },
    {
        "key":          "flex_sig_findings",
        "excel_header": "Flex sig: Fidnings ",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Follow-up Clinical Details",
        "notes":        "Note: typo in prototype header ('Fidnings') — match exactly",
    },

    # --- MDT AFTER 12 WEEKS ---
    {
        "key":          "mdt_12wk_date",
        "excel_header": "MDT (after 12 week): Date",
        "priority":     "P2",
        "method":       ExtractionMethod.REGEX,
        "source":       "Follow-up MDT header",
        "notes":        "",
    },
    {
        "key":          "mdt_12wk_decision",
        "excel_header": "MDT (after 12 week): Decision ",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome of 12-week follow-up entry",
        "notes":        "",
    },

    # --- WATCH AND WAIT ---
    {
        "key":          "ww_entry_date",
        "excel_header": "Watch and wait: Entered watch + wait, date of MDT ?",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome — 'watch and wait' phrase",
        "notes":        "",
    },
    {
        "key":          "ww_intent",
        "excel_header": "Watch and wait: Why did they enter wait (with what intent)",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "ww_frequency",
        "excel_header": "Watch and wait: Frequency?",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "MDT Outcome",
        "notes":        "",
    },
    {
        "key":          "ww_progression_date",
        "excel_header": "Watch and wait: Date of  progression",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "Follow-up MDT entries",
        "notes":        "",
    },
    {
        "key":          "ww_progression_site",
        "excel_header": "Watch and wait: Site of  progression",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "Follow-up MDT entries",
        "notes":        "",
    },
    {
        "key":          "ww_death_date",
        "excel_header": "Watch and wait: Date of death",
        "priority":     "P2",
        "method":       ExtractionMethod.LLM,
        "source":       "Follow-up MDT entries",
        "notes":        "",
    },

    # --- AI SUMMARY (Team Cloud9 addition) ---
    {
        "key":          "ai_summary",
        "excel_header": "AI Summary (Cloud9)",
        "priority":     "P1",
        "method":       ExtractionMethod.LLM,
        "source":       "All sections",
        "notes":        "2-3 sentence plain English patient journey. Always MEDIUM confidence.",
    },
]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

# key -> column definition
COLUMN_BY_KEY = {col["key"]: col for col in COLUMNS}

# key -> excel_header
HEADER_BY_KEY = {col["key"]: col["excel_header"] for col in COLUMNS}

# excel_header -> key
KEY_BY_HEADER = {col["excel_header"]: col["key"] for col in COLUMNS}

# Ordered list of excel headers (matches prototype column order)
EXCEL_COLUMN_ORDER = [col["excel_header"] for col in COLUMNS]

# Ordered list of internal keys
KEY_ORDER = [col["key"] for col in COLUMNS]


# ---------------------------------------------------------------------------
# Treatment Approach Keyword Mapping
# ---------------------------------------------------------------------------
# Used by extract_regex.py and extract_llm.py to normalise MDT decisions.

TREATMENT_APPROACH_MAP = {
    # keyword (lowercase)  ->  normalised value
    "foxtrot":              "downstaging chemotherapy",
    "capox":                "downstaging chemotherapy",
    "folfox":               "downstaging chemotherapy",
    "neoadjuvant chemo":    "downstaging chemotherapy",
    "crt":                  "downstaging nCRT",
    "chemoradiotherapy":    "downstaging nCRT",
    "chemo-radiotherapy":   "downstaging nCRT",
    "long course":          "downstaging nCRT",
    "short course":         "downstaging shortcourse RT",
    "scprt":                "downstaging shortcourse RT",
    "5x5":                  "downstaging shortcourse RT",
    "papillon":             "Papillon +/- EBRT",
    "ebrt":                 "Papillon +/- EBRT",
    "watch and wait":       "watch and wait",
    "tnt":                  "TNT",
    "total neoadjuvant":    "TNT",
    "surgery":              "straight to surgery",
    "hemicolectomy":        "straight to surgery",
    "elape":                "straight to surgery",
    "anterior resection":   "straight to surgery",
    "surgical review":      "straight to surgery",
    "right hemi":           "straight to surgery",
}


# ---------------------------------------------------------------------------
# Excel Sheet Names
# ---------------------------------------------------------------------------

SHEET_PATIENT_DATA   = "Patient Data"
SHEET_CONFIDENCE_MAP = "Confidence Map"
SHEET_VALIDATION     = "Validation Flags"


# ---------------------------------------------------------------------------
# Validation Agent Threshold
# ---------------------------------------------------------------------------

# Fields with agent_confidence below this are flagged for clinician review
# and downgraded to LOW confidence.
VALIDATION_CONFIDENCE_THRESHOLD = 0.70
