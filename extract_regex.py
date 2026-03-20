"""
extract_regex.py — Deterministic regex-based extraction for structured fields.

Populates fields that appear in predictable, labelled formats in the DOCX,
so the LLM only handles ambiguous/complex clinical fields.

Text format note: CaseText uses newline-separated cell text (not pipe-separated
like the baseline solution), so patterns are adapted accordingly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parse_docx import CaseText


@dataclass
class FieldResult:
    """Extraction result for a single field (mirrors extract_llm.FieldResult)."""
    key: str
    value: str
    evidence: str      # Verbatim quote from source text
    confidence: str    # "high", "medium", "low", "none"

# ---------------------------------------------------------------------------
# Shared patterns
# ---------------------------------------------------------------------------

# Date: DD/MM/YYYY, DD/MM/YY, DD-MM-YYYY, DD.MM.YYYY etc.
_DATE_RE = re.compile(r"\d{1,2}[/\.\-]\d{1,2}[/\.\-]\d{2,4}")

# Separator characters used between label and value (colon, en-dash, hyphen)
_SEP = r"[:\u2013\-]"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _clean_date(raw: str) -> str:
    """Normalise a raw date string to DD/MM/YYYY with zero-padded day/month."""
    if not raw:
        return ""
    raw = raw.strip()
    parts = re.split(r"[/\.\-]", raw)
    if len(parts) != 3:
        return ""
    day, month, year = parts
    if len(year) == 2:
        year = f"20{year}"
    return f"{day.zfill(2)}/{month.zfill(2)}/{year}"


def _first_match(pattern: str, text: str, flags: int = 0) -> str | None:
    """Return the first capturing group of the first match, or None."""
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _make_result(key: str, value: str, evidence: str, confidence: str) -> FieldResult:
    return FieldResult(key=key, value=value, evidence=evidence, confidence=confidence)


# ---------------------------------------------------------------------------
# Tier 1 — Demographics  (from case.demographics_text)
# ---------------------------------------------------------------------------

def _extract_mrn(text: str):
    """Return (value, evidence) for hospital/MRN number, or None."""
    m = re.search(r"Hospital\s+Number\s*[:\-]?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(0).strip()
    return None


def _extract_nhs_number(text: str):
    """Return (value, evidence) for NHS number (10 digits), or None."""
    m = re.search(r"NHS\s+Number\s*[:\-]?\s*(\d[\d\s]{8,}\d)", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        value = re.sub(r"\s+", "", raw)
        if 9 <= len(value) <= 11:
            return value, m.group(0).strip()
    return None


def _extract_dob(text: str):
    """Return (value, evidence) for date of birth, or None."""
    # Pattern: DOB or D.O.B followed by a date
    m = re.search(
        r"D\.?O\.?B\.?\s*[:\-]?\s*(" + _DATE_RE.pattern + r")",
        text,
        re.IGNORECASE,
    )
    if m:
        cleaned = _clean_date(m.group(1))
        if cleaned:
            return cleaned, m.group(0).strip()
    # Fallback: date immediately before Age/YO token
    m = re.search(
        r"(" + _DATE_RE.pattern + r")\s*(?:\(?\d{2,3}\s*(?:yr|year|yo|y\.o)|\(?Age)",
        text,
        re.IGNORECASE,
    )
    if m:
        cleaned = _clean_date(m.group(1))
        if cleaned:
            return cleaned, m.group(0).strip()
    return None


def _extract_gender(text: str):
    """Return (value, evidence) for gender: Male or Female, or None."""
    m = re.search(r"\b(Male|Female)\b", text, re.IGNORECASE)
    if m:
        return m.group(1).title(), m.group(0).strip()
    return None


def _initials_from_name(name: str) -> str:
    """Derive initials from a full name string (first + last letter)."""
    # Remove prefixes like Mr/Mrs/Dr, hyphens become spaces
    cleaned = re.sub(r"^(Mr|Mrs|Ms|Dr|Prof)\.?\s+", "", name, flags=re.IGNORECASE)
    cleaned = cleaned.replace("-", " ")
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][0].upper()
    return f"{parts[0][0].upper()}{parts[-1][0].upper()}"


def _extract_name_and_initials(text: str):
    """Return (initials, evidence) derived from the patient name field, or None."""
    # Look for explicit Name: label
    m = re.search(
        r"Name\s*[:\-]?\s*([A-Z][A-Za-z\-']+(?:\s+[A-Z][A-Za-z\-']+)+)",
        text,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        # Trim any trailing demographic label fragments
        name = re.split(r"\s+(?:Gender|DOB|D\.O\.B|NHS|Hospital)", name, flags=re.IGNORECASE)[0].strip()
        initials = _initials_from_name(name)
        if initials:
            return initials, m.group(0).strip()
    # Fallback: upper-case names between NHS Number and Gender/DOB lines
    m = re.search(
        r"NHS\s+Number[^\n]*\n+\s*([A-Z][A-Z\s\-']+[A-Z])\s*\n",
        text,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        initials = _initials_from_name(name)
        if initials:
            return initials, m.group(0).strip()
    return None


def _extract_previous_cancer(text: str):
    """
    Return ((prev_cancer_value, evidence), (prev_cancer_site_value, evidence)), or None.
    """
    # Known cancer types (excluding colorectal which is the current diagnosis)
    known_cancers = [
        (r"lymphoma", "lymphoma"),
        (r"breast\s+cancer", "breast"),
        (r"prostate\s+cancer", "prostate"),
        (r"head\s+and\s+neck\s+cancer", "head and neck"),
        (r"lung\s+cancer", "lung"),
        (r"ovarian\s+cancer", "ovarian"),
        (r"cervical\s+cancer", "cervical"),
        (r"endometrial\s+cancer", "endometrial"),
        (r"bladder\s+cancer", "bladder"),
        (r"melanoma", "melanoma"),
        (r"thyroid\s+cancer", "thyroid"),
        (r"renal\s+(?:cell\s+)?(?:carcinoma|cancer)", "renal"),
    ]

    for pattern, site_label in known_cancers:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            evidence = m.group(0).strip()
            return ("Yes", evidence), (site_label, evidence)

    # Generic "previous/prior/history of cancer" (but NOT colorectal/rectal/bowel)
    m = re.search(
        r"(?:previous|prior|history\s+of|known)\s+(?!(?:colorectal|rectal|bowel|colon|sigmoid)\s)"
        r"([a-z\s]+cancer|carcinoma|tumou?r)",
        text,
        re.IGNORECASE,
    )
    if m:
        site = m.group(1).strip()
        return ("Yes", m.group(0).strip()), (site, m.group(0).strip())

    return None


# ---------------------------------------------------------------------------
# Tier 2 — MDT date, endoscopy, biopsy, MMR
# ---------------------------------------------------------------------------

def _extract_first_mdt_date(mdt_paragraph: str):
    """Extract first date from the MDT header paragraph, or None."""
    m = _DATE_RE.search(mdt_paragraph)
    if m:
        cleaned = _clean_date(m.group(0))
        if cleaned:
            return cleaned, m.group(0).strip()
    return None


def _extract_mmr_status(text: str):
    """Return (value, evidence) for MMR status: Deficient or Proficient, or None."""
    m = re.search(r"\bMMR\s+deficient\b|\bdeficient\s+MMR\b", text, re.IGNORECASE)
    if m:
        return "Deficient", m.group(0).strip()
    m = re.search(r"\bMMR\s+proficient\b|\bproficient\s+MMR\b", text, re.IGNORECASE)
    if m:
        return "Proficient", m.group(0).strip()
    return None


def _extract_endoscopy(clinical_text: str, outcome_text: str) -> dict:
    """
    Extract endoscopy type, date, and findings.

    Returns dict of field_key -> (value, evidence) for matched fields.
    Handles patterns:
    1. TYPE DATE: findings
    2. TYPE on DATE: findings
    3. TYPE: findings (no date)
    """
    combined = f"{clinical_text}\n{outcome_text}"

    _ENDO_TYPE = r"((?:completion\s+|repeat\s+)?(?:colonoscopy|flexi\s*sig|sigmoidoscopy))"
    _DATE_PAT = r"(" + _DATE_RE.pattern + r")"
    _SEP_OPT = r"\s*" + _SEP + r"?\s*"

    # Pattern 1: TYPE DATE [sep] findings
    p_date_direct = _ENDO_TYPE + r"\s+" + _DATE_PAT + _SEP_OPT + r"([^\n]*)"
    # Pattern 2: TYPE on DATE [sep] findings
    p_date_on = _ENDO_TYPE + r"\s+on\s+" + _DATE_PAT + _SEP_OPT + r"([^\n]*)"
    # Pattern 3: TYPE [sep] findings (no date)
    p_no_date = _ENDO_TYPE + r"\s*" + _SEP + r"\s*([^\n]+)"

    for pattern, has_date in [
        (p_date_direct, True),
        (p_date_on, True),
        (p_no_date, False),
    ]:
        m = re.search(pattern, combined, re.IGNORECASE)
        if not m:
            continue

        raw_type = m.group(1)
        if has_date:
            raw_date = m.group(2)
            findings = m.group(3).strip()
        else:
            raw_date = ""
            findings = m.group(2).strip()

        # Classify endoscopy type - only mark as "complete" if explicitly stated
        if re.search(r"flexi|sigmoidoscopy", raw_type, re.IGNORECASE):
            endo_type = "flexi sig"
        elif re.search(r"complete|ileocaecal|terminal\s+ileum|caecum", raw_type + " " + findings, re.IGNORECASE):
            endo_type = "Colonoscopy complete"
        else:
            endo_type = "Colonoscopy"
        evidence = m.group(0).strip()

        field_results = {}
        field_results["endoscopy_type"] = (endo_type, evidence)
        if findings:
            field_results["endoscopy_findings"] = (findings, evidence)

        if has_date and raw_date:
            cleaned_date = _clean_date(raw_date)
            field_results["endoscopy_date"] = (cleaned_date if cleaned_date else "Missing", evidence)
        else:
            field_results["endoscopy_date"] = ("Missing", evidence)

        # Biopsy date: infer from endoscopy date if findings mention cancer/biopsy
        if has_date and raw_date and re.search(
            r"adenocarcinoma|carcinoma|cancer|biopsy", findings, re.IGNORECASE
        ):
            cleaned_date = _clean_date(raw_date)
            if cleaned_date:
                field_results["biopsy_date"] = (cleaned_date, evidence)

        return field_results

    return {}


def _extract_biopsy_result(staging_text: str, outcome_text: str):
    """Extract biopsy/histology result from staging or outcome text, or None."""
    combined = f"{staging_text}\n{outcome_text}"

    # Look for explicit Diagnosis: label first
    m = re.search(r"Diagnosis\s*[:\-]\s*([^\n]+)", combined, re.IGNORECASE)
    if m:
        diagnosis = m.group(1).strip()
        if re.search(r"adenocarcinoma|adenoma|dysplasia|carcinoma", diagnosis, re.IGNORECASE):
            return diagnosis, m.group(0).strip()

    # Free text pattern
    m = re.search(
        r"(adenocarcinoma[^\n]*|adenoma[^\n]*|dysplasia[^\n]*)",
        combined,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), m.group(0).strip()

    return None


# ---------------------------------------------------------------------------
# Tier 3 — Staging helpers
# ---------------------------------------------------------------------------

def _extract_staging_components(text: str) -> dict:
    """
    Extract T, N, M, EMVI, CRM, PSW staging values from a text block.

    Returns dict of component_name -> (value, evidence).
    """
    results = {}

    # T staging
    t_m = re.search(
        r"(?:^|\s)(?:mr|ct|c|p)?T\s*([0-4](?:[a-d]|sm\d(?:/\d)?)?)\b",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if t_m:
        results["T"] = (t_m.group(1), t_m.group(0).strip())

    # N staging
    n_m = re.search(
        r"(?:^|\s)(?:mr|ct|c|p)?N\s*([0-3][a-c]?)\b",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if n_m:
        results["N"] = (n_m.group(1), n_m.group(0).strip())

    # M staging
    m_m = re.search(
        r"(?:^|\s)(?:mr|ct|c|p)?M\s*([0-1][a-c]?)\b",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if m_m:
        results["M"] = (m_m.group(1), m_m.group(0).strip())

    # EMVI — normalise +/- to positive/negative
    emvi_m = re.search(
        r"EMVI\s*[:\-]?\s*(positive|negative|clear|unsafe|\+|\u2013|-)",
        text,
        re.IGNORECASE,
    )
    if emvi_m:
        raw = emvi_m.group(1)
        norm = {"+": "positive", "-": "negative", "\u2013": "negative"}.get(raw.lower(), raw.lower())
        if norm in ("positive", "negative"):
            results["EMVI"] = (norm, emvi_m.group(0).strip())

    # CRM — normalise unsafe->threatened, -/endash->clear
    crm_m = re.search(
        r"CRM(?:/ISP)?\s*[:\-]?\s*(clear|unsafe|threatened|involved|\-|\u2013)",
        text,
        re.IGNORECASE,
    )
    if crm_m:
        raw = crm_m.group(1)
        norm_map = {"unsafe": "threatened", "-": "clear", "\u2013": "clear"}
        norm = norm_map.get(raw.lower(), raw.lower())
        if norm in ("clear", "threatened", "involved"):
            results["CRM"] = (norm, crm_m.group(0).strip())

    # PSW — normalise -/endash->clear
    psw_m = re.search(
        r"PSW\s*[:\-]?\s*(clear|unsafe|\-|\u2013)",
        text,
        re.IGNORECASE,
    )
    if psw_m:
        raw = psw_m.group(1)
        norm_map = {"-": "clear", "\u2013": "clear"}
        norm = norm_map.get(raw.lower(), raw.lower())
        if norm in ("clear", "unsafe"):
            results["PSW"] = (norm, psw_m.group(0).strip())

    return results


# ---------------------------------------------------------------------------
# Tier 3 — MRI staging
# ---------------------------------------------------------------------------

def _extract_mri_segment(text: str) -> str:
    """Return the line most likely containing MRI staging information."""
    for line in text.splitlines():
        if re.search(r"\bMR(?:I\b| rectum\b| pelvis\b| staging\b)", line, re.IGNORECASE):
            return line.strip()
    return ""


def _extract_mri_fields(clinical_text: str, outcome_text: str) -> dict:
    """Extract baseline MRI date and staging values. Returns dict of field_key -> (value, evidence)."""
    combined = f"{clinical_text}\n{outcome_text}"
    results = {}

    mri_seg = _extract_mri_segment(combined)
    if not mri_seg:
        return results

    # Date: MRI [qualifier] [on] DATE
    date_m = re.search(
        r"\bMR(?:I)?(?:\s+(?:pelvis|rectum|staging|stage))?"
        r"(?:\s+on)?\s+(" + _DATE_RE.pattern + r")",
        mri_seg,
        re.IGNORECASE,
    )
    if date_m:
        cleaned = _clean_date(date_m.group(1))
        if cleaned:
            results["baseline_mri_date"] = (cleaned, date_m.group(0).strip())

    staging = _extract_staging_components(mri_seg)
    if "T" in staging:
        results["baseline_mri_mrT"] = staging["T"]
    if "N" in staging:
        results["baseline_mri_mrN"] = staging["N"]
    if "EMVI" in staging:
        results["baseline_mri_mrEMVI"] = staging["EMVI"]
    if "CRM" in staging:
        results["baseline_mri_mrCRM"] = staging["CRM"]
    if "PSW" in staging:
        results["baseline_mri_mrPSW"] = staging["PSW"]

    return results


# ---------------------------------------------------------------------------
# Tier 3 — CT staging
# ---------------------------------------------------------------------------

def _extract_ct_segment(text: str) -> str:
    """Return the first line containing CT (excluding PET-CT)."""
    for line in text.splitlines():
        if re.search(r"PET[\-\u2013]?CT", line, re.IGNORECASE):
            continue
        if re.search(r"\bCT\b", line, re.IGNORECASE):
            return line.strip()
    return ""


def _extract_ct_fields(clinical_text: str, outcome_text: str) -> dict:
    """Extract baseline CT date, staging, and incidental findings. Returns dict of field_key -> (value, evidence)."""
    combined = f"{clinical_text}\n{outcome_text}"
    results = {}

    ct_seg = _extract_ct_segment(combined)
    if not ct_seg:
        return results

    # Date: CT [qualifier] [on] DATE
    date_m = re.search(
        r"\bCT(?:\s+(?:TAP|abdomen|pelvis|thorax|chest|colonography|[a-zA-Z]+))?"
        r"(?:\s+on)?\s+(" + _DATE_RE.pattern + r")",
        ct_seg,
        re.IGNORECASE,
    )
    if date_m:
        cleaned = _clean_date(date_m.group(1))
        if cleaned:
            results["baseline_ct_date"] = (cleaned, date_m.group(0).strip())

    staging = _extract_staging_components(ct_seg)
    if "T" in staging:
        results["baseline_ct_T"] = staging["T"]
    if "N" in staging:
        results["baseline_ct_N"] = staging["N"]
    if "EMVI" in staging:
        results["baseline_ct_EMVI"] = staging["EMVI"]

    # M staging: infer from metastasis prose
    if re.search(
        r"no\s+(?:distant\s+)?(?:metastases?|metastatic|mets|liver\s+metastases?|distant\s+disease)",
        ct_seg,
        re.IGNORECASE,
    ):
        results["baseline_ct_M"] = ("0", ct_seg)
    elif re.search(
        r"(?:liver\s+lesion|lung\s+metastases?|metastases?|metastatic\s+disease)",
        ct_seg,
        re.IGNORECASE,
    ):
        m_val = staging["M"][0] if "M" in staging else "1"
        results["baseline_ct_M"] = (m_val, ct_seg)
    elif "M" in staging:
        results["baseline_ct_M"] = staging["M"]

    # Incidental findings
    inc_m = re.search(r"incidental\s+([^\n]+)", ct_seg, re.IGNORECASE)
    if inc_m:
        detail = inc_m.group(1).strip()
        results["baseline_ct_incidental_yn"] = ("Y", inc_m.group(0).strip())
        results["baseline_ct_incidental_detail"] = (detail, inc_m.group(0).strip())

    return results


# ---------------------------------------------------------------------------
# Tier 4 — Treatment approach
# ---------------------------------------------------------------------------

def _extract_treatment_approach(outcome_text: str):
    """
    Classify the MDT treatment approach from the outcome row.

    Mappings follow SYSTEM_INSTRUCTION rule 22 in extract_llm.py.
    Returns (value, evidence) or None.
    """
    # TNT must be checked before individual CRT/chemo to avoid partial matches
    m = re.search(r"\bTNT\b", outcome_text, re.IGNORECASE)
    if m:
        return "TNT", m.group(0).strip()

    m = re.search(r"\bFOXTROT\b|\bCAPOX\b|\bFOLFOX\b|neoadjuvant\s+chemotherapy", outcome_text, re.IGNORECASE)
    if m:
        return "downstaging chemotherapy", m.group(0).strip()

    m = re.search(r"\bCRT\b|chemoradiotherapy|long\s+course\s+radiotherapy|neoadjuvant\s+CRT", outcome_text, re.IGNORECASE)
    if m:
        return "downstaging nCRT", m.group(0).strip()

    m = re.search(r"short\s+course\s+(?:radio)?therapy|\bSCPRT\b|5\s*[xX]\s*5\s*Gy", outcome_text, re.IGNORECASE)
    if m:
        return "downstaging shortcourse RT", m.group(0).strip()

    m = re.search(r"\bPapillon\b|contact\s+radiotherapy|\bEBRT\b", outcome_text, re.IGNORECASE)
    if m:
        return "Papillon +/- EBRT", m.group(0).strip()

    # Ambiguous phrasing ("surgical review") should not be treated as a
    # confirmed surgery decision unless a definitive surgery term is present.
    review_m = re.search(r"surgical\s+review|refer\s+for\s+surgical\s+review", outcome_text, re.IGNORECASE)
    definitive_m = re.search(
        r"\bsurgery\b|hemicolectomy|resection|anterior\s+resection|right\s+hemicolectomy"
        r"|\beLAPE\b|\bESD\b|local\s+excision|\bTEMS\b|\bTAMIS\b",
        outcome_text,
        re.IGNORECASE,
    )
    if review_m and not definitive_m:
        return None

    if definitive_m:
        return "straight to surgery", definitive_m.group(0).strip()

    m = re.search(r"watch\s+and\s+wait|active\s+surveillance", outcome_text, re.IGNORECASE)
    if m:
        return "watch and wait", m.group(0).strip()

    return None


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def regex_extract(case: CaseText) -> dict:
    """
    Extract deterministic fields from structured DOCX sections.

    Returns a dict of field_key -> FieldResult ONLY for fields that were
    successfully matched. Never returns empty / guessed values.
    """
    results = {}

    demo = case.demographics_text
    staging = case.staging_text
    clinical = case.clinical_text
    outcome = case.outcome_text
    mdt_para = case.mdt_date_paragraph

    # ── Demographics ──────────────────────────────────────────────────────
    res = _extract_mrn(demo)
    if res:
        results["mrn"] = _make_result("mrn", res[0], res[1], "high")

    res = _extract_nhs_number(demo)
    if res:
        results["nhs_number"] = _make_result("nhs_number", res[0], res[1], "high")

    res = _extract_dob(demo)
    if res:
        results["dob"] = _make_result("dob", res[0], res[1], "high")

    res = _extract_gender(demo)
    if res:
        results["gender"] = _make_result("gender", res[0], res[1], "high")

    res = _extract_name_and_initials(demo)
    if res:
        results["initials"] = _make_result("initials", res[0], res[1], "high")

    prev_res = _extract_previous_cancer(f"{demo}\n{clinical}\n{outcome}")
    if prev_res:
        (pc_val, pc_ev), (pcs_val, pcs_ev) = prev_res
        results["previous_cancer"] = _make_result("previous_cancer", pc_val, pc_ev, "high")
        results["previous_cancer_site"] = _make_result("previous_cancer_site", pcs_val, pcs_ev, "high")

    # ── MDT date ──────────────────────────────────────────────────────────
    res = _extract_first_mdt_date(mdt_para)
    if res:
        results["first_mdt_date"] = _make_result("first_mdt_date", res[0], res[1], "high")

    # ── MMR status ────────────────────────────────────────────────────────
    res = _extract_mmr_status(f"{staging}\n{clinical}\n{outcome}")
    if res:
        results["mmr_status"] = _make_result("mmr_status", res[0], res[1], "high")

    # ── Endoscopy + biopsy date ───────────────────────────────────────────
    endo_results = _extract_endoscopy(clinical, outcome)
    for field_key, (value, evidence) in endo_results.items():
        confidence = "medium" if field_key == "biopsy_date" else "high"
        results[field_key] = _make_result(field_key, value, evidence, confidence)

    # ── Biopsy result ─────────────────────────────────────────────────────
    res = _extract_biopsy_result(staging, outcome)
    if res:
        results["biopsy_result"] = _make_result("biopsy_result", res[0], res[1], "high")

    # ── MRI staging ───────────────────────────────────────────────────────
    mri_results = _extract_mri_fields(clinical, outcome)
    for field_key, (value, evidence) in mri_results.items():
        results[field_key] = _make_result(field_key, value, evidence, "high")

    # ── CT staging ────────────────────────────────────────────────────────
    ct_results = _extract_ct_fields(clinical, outcome)
    for field_key, (value, evidence) in ct_results.items():
        confidence = "medium" if field_key == "baseline_ct_M" else "high"
        results[field_key] = _make_result(field_key, value, evidence, confidence)

    # ── Treatment approach ────────────────────────────────────────────────
    res = _extract_treatment_approach(outcome)
    if res:
        results["first_mdt_treatment_approach"] = _make_result(
            "first_mdt_treatment_approach", res[0], res[1], "high"
        )

    return results
