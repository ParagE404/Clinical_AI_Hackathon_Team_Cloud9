import unittest

from extract_regex import _extract_treatment_approach
from extract_llm import CaseResult, FieldResult
from parse_docx import CaseText
from validate_agent import validate_case


class _StubClient:
    def __init__(self, payload: str):
        self.payload = payload

    def generate(self, **kwargs):
        return {"text": self.payload}


class TestRootPipelineRegressions(unittest.TestCase):
    def test_validation_ignores_off_schema_keys(self):
        case = CaseText(
            case_index=0,
            mdt_date_paragraph="MDT 01/01/2025",
            demographics_text="",
            staging_text="",
            clinical_text="",
            outcome_text="",
            full_text="[ROW 1]: test",
            row_texts={},
        )
        extraction = CaseResult(
            case_index=0,
            fields={
                "dob": FieldResult("dob", "01/01/1990", "01/01/1990", "high"),
            },
            raw_llm_response="",
            source_text=case.full_text,
        )
        client = _StubClient(
            '[{"field_key":"age","issue_type":"missing_data","description":"off schema","suggested_value":"65","severity":"warning"},'
            '{"field_key":"dob","issue_type":"incorrect_value","description":"bad date","suggested_value":"02/01/1990","severity":"critical"}]'
        )

        result = validate_case(case, extraction, client)
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].field_key, "dob")

    def test_treatment_review_only_is_not_straight_to_surgery(self):
        res = _extract_treatment_approach("Plan: refer for surgical review and rediscuss")
        self.assertIsNone(res)

    def test_treatment_definitive_surgery_still_maps(self):
        res = _extract_treatment_approach("Plan: refer for surgical review and then resection")
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "straight to surgery")


if __name__ == "__main__":
    unittest.main()
