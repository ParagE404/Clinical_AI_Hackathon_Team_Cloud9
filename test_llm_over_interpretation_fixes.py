#!/usr/bin/env python3
"""
Test script to verify LLM over-interpretation fixes.
Validates that the SYSTEM_INSTRUCTION changes prevent common over-interpretation issues.
"""

import unittest
from extract_llm import SYSTEM_INSTRUCTION
from build_dataframe import build_dataframes
from extract_llm import CaseResult, FieldResult
from schema import COLUMNS


class TestOverInterpretationFixes(unittest.TestCase):
    """Test that system instruction prevents over-interpretation."""

    def test_rule_3_evidence_completeness(self):
        """Test that Rule 3 requires complete evidence quotes."""
        self.assertIn("COMPLETE sentence or line", SYSTEM_INSTRUCTION)
        self.assertIn("not just a minimum matching fragment", SYSTEM_INSTRUCTION)
        self.assertIn("entire staging line", SYSTEM_INSTRUCTION)

    def test_rule_13_inferred_confidence(self):
        """Test that Rule 13 requires medium confidence for inferred staging."""
        self.assertIn('set confidence to "medium"', SYSTEM_INSTRUCTION)
        self.assertIn("not explicit staging codes", SYSTEM_INSTRUCTION)

    def test_rule_16_previous_cancer_no_assumption(self):
        """Test that Rule 16 doesn't assume 'No' when cancer not mentioned."""
        # Should NOT contain the old "If no prior cancer mentioned, answer 'No'"
        self.assertNotIn('If no prior cancer mentioned, answer "No"', SYSTEM_INSTRUCTION)
        # Should contain the new conditional logic
        self.assertIn("explicitly denied", SYSTEM_INSTRUCTION)
        self.assertIn("simply not discussed, leave blank", SYSTEM_INSTRUCTION)

    def test_rule_17_previous_cancer_site_blank(self):
        """Test that Rule 17 allows blank previous_cancer_site."""
        self.assertIn("Leave blank if previous_cancer is blank", SYSTEM_INSTRUCTION)

    def test_rule_18_colonoscopy_not_complete_by_default(self):
        """Test that Rule 18 only uses 'complete' when explicitly stated."""
        # Should NOT contain the old "default to 'Colonoscopy complete'"
        self.assertNotIn("default to 'Colonoscopy complete'", SYSTEM_INSTRUCTION)
        # Should contain the new stricter logic
        self.assertIn("ONLY if explicitly described as complete", SYSTEM_INSTRUCTION)
        self.assertIn('classify as "Colonoscopy"', SYSTEM_INSTRUCTION)
        self.assertIn("reaching ileocaecal valve", SYSTEM_INSTRUCTION)
        self.assertIn("reaching terminal ileum", SYSTEM_INSTRUCTION)

    def test_rule_22_surgical_review_not_surgery(self):
        """Test that Rule 22 doesn't classify surgical review as surgery."""
        # Should NOT contain the old mapping
        self.assertNotIn("surgical review/refer for surgical review", SYSTEM_INSTRUCTION)
        # Should contain clarification about referrals
        self.assertIn("ONLY a referral for review or discussion", SYSTEM_INSTRUCTION)
        self.assertIn("refer for surgical review", SYSTEM_INSTRUCTION)
        self.assertIn("discuss possible surgery", SYSTEM_INSTRUCTION)
        self.assertIn("return empty", SYSTEM_INSTRUCTION)

    def test_endo_map_handles_standalone_colonoscopy(self):
        """Test that build_dataframe handles standalone 'Colonoscopy' value."""
        from schema import KEY_TO_HEADER

        # Create a mock case result with standalone "Colonoscopy"
        fields = {col.key: FieldResult(key=col.key, value="", evidence="", confidence="none")
                  for col in COLUMNS}
        fields["endoscopy_type"] = FieldResult(
            key="endoscopy_type",
            value="Colonoscopy",  # Not "Colonoscopy complete"
            evidence="Colonoscopy: findings...",
            confidence="high"
        )

        case_result = CaseResult(
            case_index=0,
            fields=fields,
            raw_llm_response="",
            source_text=""
        )

        # Build dataframes
        data_df, evidence_df, confidence_df = build_dataframes([case_result])

        # Check that the value is preserved (not converted to "Colonoscopy complete")
        endo_header = KEY_TO_HEADER["endoscopy_type"]
        endo_value = data_df[endo_header].iloc[0]
        self.assertEqual(endo_value, "Colonoscopy")

    def test_endo_inference_logic(self):
        """Test that endoscopy inference doesn't default to complete."""
        from schema import KEY_TO_HEADER

        # Create a mock case result with no endoscopy_type but evidence
        fields = {col.key: FieldResult(key=col.key, value="", evidence="", confidence="none")
                  for col in COLUMNS}

        # Case 1: Just "colonoscopy" without completeness indicator
        fields["endoscopy_type"] = FieldResult(
            key="endoscopy_type",
            value="",  # Empty - will be inferred
            evidence="colonoscopy findings",
            confidence="none"
        )

        case_result = CaseResult(
            case_index=0,
            fields=fields,
            raw_llm_response="",
            source_text=""
        )

        # Build dataframes - this triggers inference logic
        data_df, _, _ = build_dataframes([case_result])

        # Should infer "Colonoscopy" (not "Colonoscopy complete")
        endo_header = KEY_TO_HEADER["endoscopy_type"]
        endo_value = data_df[endo_header].iloc[0]
        self.assertEqual(endo_value, "Colonoscopy")


class TestSystemInstructionIntegrity(unittest.TestCase):
    """Test that system instruction maintains core principles."""

    def test_extract_only_explicit_info(self):
        """Test that Rule 1 is preserved."""
        self.assertIn("Extract ONLY information explicitly stated", SYSTEM_INSTRUCTION)

    def test_blank_better_than_wrong(self):
        """Test that Rule 5 is preserved."""
        self.assertIn("blank value is ALWAYS better than a wrong value", SYSTEM_INSTRUCTION)

    def test_verbatim_evidence_required(self):
        """Test that evidence must be verbatim."""
        self.assertIn("verbatim substring", SYSTEM_INSTRUCTION)
        self.assertIn("Never paraphrase", SYSTEM_INSTRUCTION)


def main():
    """Run all tests."""
    print("=" * 60)
    print("LLM Over-Interpretation Fixes Test Suite")
    print("=" * 60)
    print()

    # Run tests
    suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("✅ All tests passed!")
        print("The system instruction changes are correct.")
        return 0
    else:
        print("❌ Some tests failed!")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
