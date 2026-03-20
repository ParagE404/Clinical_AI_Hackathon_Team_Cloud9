# LLM Over-Interpretation Fixes - Implementation Summary

## Overview

This document summarizes the systematic fixes applied to prevent LLM over-interpretation issues in the Clinical AI Hackathon Team Cloud9 extraction pipeline. The goal was to ensure that extracted data matches exactly what a clinician would expect when comparing the source Word document with the generated Excel output.

## Core Principle

**A blank cell is far better than a wrong value.** Clinicians will immediately spot fabricated or over-interpreted data, destroying trust in the system. Every filled cell must be defensible with verbatim evidence from the source document.

---

## Changes Made

### 1. Rule 3: Strengthen Evidence Quote Requirements

**File:** `extract_llm.py:81`

**Before:**
```
3. The "evidence" MUST be a verbatim substring from the SOURCE TEXT. Never paraphrase.
```

**After:**
```
3. The "evidence" MUST be a verbatim substring from the SOURCE TEXT. Never paraphrase.
   The evidence quote should be the COMPLETE sentence or line containing the relevant
   information, not just a minimum matching fragment. For MRI staging lines, quote the
   entire staging line (e.g., 'T3c, N1c, CRM/ISP unsafe, EMVI positive, PSW clear'),
   not individual values.
```

**Rationale:** Partial evidence quotes appeared sloppy to validators. Complete sentences provide full context and allow clinicians to verify the extraction themselves.

---

### 2. Rule 13: Require Medium Confidence for Inferred Staging

**File:** `extract_llm.py:95`

**Before:**
```
13. For CT M staging: infer "0" from "no metastases"/"no distant disease"/...
    Infer "1" from "metastases"/"liver lesions"/"lung metastases"/...
```

**After:**
```
13. For CT M staging: infer "0" from "no metastases"/"no distant disease"/...
    Infer "1" from "metastases"/"liver lesions"/"lung metastases"/...
    When inferring M or N values from descriptive text (not explicit staging codes),
    set confidence to "medium", not "high".
```

**Rationale:** While clinically defensible, inferred staging values are interpretations, not explicit extractions. Medium confidence signals this to reviewers.

---

### 3. Rule 16: Don't Assume "No" for Previous Cancer

**File:** `extract_llm.py:100`

**Before:**
```
16. For previous_cancer: answer "Yes" ONLY for cancers OTHER than the current colorectal
    diagnosis. If no prior cancer mentioned, answer "No".
```

**After:**
```
16. For previous_cancer: answer "Yes" ONLY for cancers OTHER than the current colorectal
    diagnosis. If prior cancer is explicitly denied or a full history section has no
    mention, answer "No". If the topic is simply not discussed, leave blank.
```

**Rationale:** Absence of information ≠ "No". If the source text doesn't discuss previous cancer, the LLM shouldn't fabricate a negative answer.

---

### 4. Rule 17: Allow Blank Previous Cancer Site

**File:** `extract_llm.py:101`

**Before:**
```
17. For previous_cancer_site: state the site (e.g. "breast", "lymphoma", "prostate").
    "N/A" if previous_cancer is "No".
```

**After:**
```
17. For previous_cancer_site: state the site (e.g. "breast", "lymphoma", "prostate").
    Leave blank if previous_cancer is blank. "N/A" if previous_cancer is "No".
```

**Rationale:** Consistency with Rule 16 - if previous_cancer is blank, the site should also be blank.

---

### 5. Rule 18: Only Use "Complete" When Explicitly Stated

**File:** `extract_llm.py:104`

**Before:**
```
18. For endoscopy_type: classify as "Colonoscopy complete" (if colonoscopy reaches
    ileocaecal valve, described as complete, or simply described as "Colonoscopy"
    with findings — default to "Colonoscopy complete" unless explicitly stated as
    incomplete), "incomplete colonoscopy" (only if explicitly stated as incomplete),
    or "flexi sig" (flexible sigmoidoscopy / flexi sig).
```

**After:**
```
18. For endoscopy_type: classify as "Colonoscopy complete" ONLY if explicitly described
    as complete, reaching ileocaecal valve, or reaching terminal ileum. If the text
    just says "Colonoscopy:" with findings (without completeness stated), classify as
    "Colonoscopy". Use "incomplete colonoscopy" only if explicitly stated as incomplete.
    For flexible sigmoidoscopy, classify as "flexi sig".
```

**Rationale:** The word "complete" was being added when it wasn't in the source text. This is over-interpretation. If the source says "Colonoscopy:", the output should be "Colonoscopy", not "Colonoscopy complete".

---

### 6. Rule 22: Surgical Review Is Not Surgery

**File:** `extract_llm.py:110-119`

**Before:**
```
22. Classify the MDT decision using these exact mappings:
    ...
    - Surgery/hemicolectomy/resection/... → "straight to surgery"
    - "surgical review" or "refer for surgical review" alone is ambiguous and should
      NOT be classified as "straight to surgery" unless a definitive surgery term is
      also present
    - Watch and wait/active surveillance → "watch and wait"
    - If the outcome is for further investigations only (e.g. "for colonoscopy",
      "for MRI", "rediscuss"), return ""
```

**After:**
```
22. Classify the MDT decision using these exact mappings:
    ...
    - Surgery/hemicolectomy/resection/... → "straight to surgery"
    - Watch and wait/active surveillance → "watch and wait"
    - If the outcome is ONLY a referral for review or discussion (e.g. "refer for
      surgical review", "discuss possible surgery", "for surgical consultation"),
      return empty — this is not a treatment decision, just a referral.
    - If the outcome is for further investigations only (e.g. "for colonoscopy",
      "for MRI", "rediscuss"), return empty.
```

**Rationale:** A referral for surgical review is a consultation, not a surgery decision. Mapping "refer for surgical review" to "straight to surgery" is incorrect over-interpretation.

---

### 7. Update Endoscopy Normalization Map

**File:** `build_dataframe.py:87-94`

**Before:**
```python
endo_map = {
    "colonoscopy": "Colonoscopy complete",  # ← Auto-upgraded to complete
    "colonoscopy complete": "Colonoscopy complete",
    "complete colonoscopy": "Colonoscopy complete",
    "incomplete colonoscopy": "incomplete colonoscopy",
    "flexi sig": "flexi sig",
    "flexible sigmoidoscopy": "flexi sig",
}
```

**After:**
```python
endo_map = {
    "colonoscopy": "Colonoscopy",  # ← Standalone colonoscopy (not stated as complete)
    "colonoscopy complete": "Colonoscopy complete",
    "complete colonoscopy": "Colonoscopy complete",
    "incomplete colonoscopy": "incomplete colonoscopy",
    "flexi sig": "flexi sig",
    "flexible sigmoidoscopy": "flexi sig",
}
```

**Rationale:** The normalization map was forcing "colonoscopy" to become "Colonoscopy complete", which contradicts the fix in Rule 18.

---

### 8. Update Endoscopy Inference Logic

**File:** `build_dataframe.py:37-45`

**Before:**
```python
elif "colonoscop" in combined_lower:
    if "incomplete" in combined_lower:
        endo_type_fr.value = "incomplete colonoscopy"
    else:
        endo_type_fr.value = "Colonoscopy complete"  # ← Default to complete
    endo_type_fr.confidence = "medium"
```

**After:**
```python
elif "colonoscop" in combined_lower:
    if "incomplete" in combined_lower:
        endo_type_fr.value = "incomplete colonoscopy"
    elif "complete" in combined_lower or "ileocaecal" in combined_lower or "terminal ileum" in combined_lower:
        endo_type_fr.value = "Colonoscopy complete"
    else:
        # Just "colonoscopy" without completeness indicator
        endo_type_fr.value = "Colonoscopy"
    endo_type_fr.confidence = "medium"
```

**Rationale:** The fallback inference logic was also defaulting to "Colonoscopy complete", which needed to be aligned with the Rule 18 fix.

---

## Testing

### Test Suite Created

A comprehensive test suite (`test_llm_over_interpretation_fixes.py`) was created with 11 tests covering:

1. ✅ Rule 3: Evidence completeness requirements
2. ✅ Rule 13: Inferred confidence levels
3. ✅ Rule 16: Previous cancer assumptions
4. ✅ Rule 17: Previous cancer site blank handling
5. ✅ Rule 18: Colonoscopy completeness
6. ✅ Rule 22: Surgical review mapping
7. ✅ Endoscopy map standalone value handling
8. ✅ Endoscopy inference logic
9. ✅ Core principle: Extract only explicit info
10. ✅ Core principle: Blank better than wrong
11. ✅ Core principle: Verbatim evidence required

### All Tests Pass

```
Ran 11 tests in 0.018s

OK
✅ All tests passed!
The system instruction changes are correct.
```

### Existing Tests Still Pass

- ✅ `test_llm_fixes.py`: 4/4 tests pass
- ✅ `test_root_pipeline_regressions.py`: 3/3 tests pass
- ✅ Baseline solution tests: 16/16 tests pass

### Pipeline Verification

- ✅ Pipeline can rebuild from JSON without errors
- ✅ DataFrame generation works correctly with new logic
- ✅ Standalone "Colonoscopy" values are preserved (not upgraded to "complete")

---

## Impact Summary

| Issue | Before | After |
|-------|--------|-------|
| **Endoscopy type** | "Colonoscopy complete" (added word "complete") | "Colonoscopy" (exact match) |
| **Treatment approach** | "refer for surgical review" → "straight to surgery" | "refer for surgical review" → blank |
| **Previous cancer** | No mention → "No" (assumption) | No mention → blank |
| **Previous cancer site** | parent blank → "N/A" | parent blank → blank |
| **Evidence quotes** | Partial fragments | Complete sentences |
| **Inferred staging** | confidence: "high" | confidence: "medium" |

---

## Files Modified

1. **extract_llm.py** - Updated SYSTEM_INSTRUCTION rules 3, 13, 16, 17, 18, 22
2. **build_dataframe.py** - Updated endo_map and inference logic

---

## Next Steps (Requires LLM Backend)

To fully validate these fixes, the following steps require an LLM backend (Ollama or Gemini):

1. **Run full pipeline on all 50 cases:**
   ```bash
   python main.py
   ```

2. **Manual clinician-eye review:**
   - Open `data/hackathon-mdt-outcome-proformas.docx` side by side with `output/generated-database-cloud9.xlsx`
   - Pick 5-10 cases at random
   - For each case, verify: "Does this Excel row match what I'd expect from the Word doc?"
   - Look for over-interpretations (filled cells that shouldn't be filled)
   - Look for under-extractions (blank cells that should be filled)

3. **Re-run validation:**
   ```bash
   python main.py --workers 5
   ```
   - Compare validation report with previous baseline
   - Target: 60%+ cases passing, <10 issues per 10 cases

---

## Acceptance Criteria Status

- ✅ SYSTEM_INSTRUCTION rules 16, 18, 22 updated to prevent over-interpretation
- ✅ Evidence quality instruction strengthened (complete sentences, not fragments)
- ✅ Inferred CT staging uses `confidence: "medium"` not "high"
- ✅ `build_dataframe.py` handles standalone "Colonoscopy" value
- ✅ All existing tests pass
- ✅ New comprehensive test suite created and passing
- ⏳ Full pipeline run on all 50 cases (requires LLM backend)
- ⏳ Validation report improvement verification (requires LLM backend)
- ⏳ Manual spot-check: 5+ random cases (requires LLM backend + human review)
- ⏳ No over-interpretations remaining (requires validation run)

---

## Conclusion

All code-level fixes have been implemented and tested. The system instruction changes systematically address the five main over-interpretation patterns identified in the validation report:

1. ✅ Endoscopy type over-classification
2. ✅ Treatment approach over-interpretation
3. ✅ Previous cancer assumptions
4. ✅ Inferred staging confidence
5. ✅ Partial evidence quotes

The changes preserve the core principle: **every filled cell must be defensible with verbatim evidence from the source document**. The pipeline is now ready for validation runs once an LLM backend is available.
