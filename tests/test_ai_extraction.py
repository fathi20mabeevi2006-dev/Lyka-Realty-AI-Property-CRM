"""
tests/test_ai_extraction.py
FR-02 / FR-03 — AI extraction via the backend, offline fallback and the
strict validation layer. No network is required: the offline provider is
selected explicitly, so these tests are deterministic and never spend API
credits.

Run:  python -m unittest discover -s tests -v
"""

import unittest

from services.ai_extract import analyse_enquiry, provider_status
from services.lead_schema import (
    EnquiryValidationError, validate_enquiry, validate_extraction,
    derive_missing_and_questions, MAX_ENQUIRY_LENGTH,
)


class ValidationTests(unittest.TestCase):
    def test_empty_enquiry_rejected(self):
        with self.assertRaises(EnquiryValidationError):
            validate_enquiry("   ")

    def test_short_enquiry_rejected(self):
        with self.assertRaises(EnquiryValidationError):
            validate_enquiry("hi")

    def test_overlong_enquiry_rejected(self):
        with self.assertRaises(EnquiryValidationError):
            validate_enquiry("a" * (MAX_ENQUIRY_LENGTH + 1))

    def test_validator_never_raises_on_junk(self):
        fields, errors, warnings = validate_extraction({"bedrooms": "many",
                                                         "budget": "??"})
        self.assertIsInstance(fields, dict)
        self.assertTrue(errors)

    def test_validator_ignores_unknown_choice(self):
        fields, errors, warnings = validate_extraction({"lead_type": "tourist"})
        self.assertIsNone(fields["lead_type"])
        self.assertFalse(errors)

    def test_budget_min_greater_than_max_is_rejected(self):
        fields, errors, _w = validate_extraction(
            {"budget_min": 5_000_000, "budget_max": 1_000_000})
        self.assertTrue(errors)
        self.assertIsNone(fields["budget_min"])

    def test_missing_fields_and_questions_are_derived(self):
        missing, questions = derive_missing_and_questions({})
        self.assertIn("budget", missing)
        self.assertIn("preferred_location", missing)
        self.assertTrue(questions)


class ExtractionTests(unittest.TestCase):
    ENQUIRY = ("Hi I am Rahul, I want a 2 bedroom apartment in Dubai Marina "
               "with swimming pool, budget around AED 1.8 million, ready in "
               "3 months. Call me on +971 50 123 4567 or rahul@example.com")

    def test_offline_provider_is_deterministic_and_flagged_degraded(self):
        result = analyse_enquiry(self.ENQUIRY, provider="offline")
        self.assertEqual(result["provider"], "offline-heuristic")
        self.assertTrue(result["degraded"])
        fields = result["fields"]
        self.assertEqual(fields["bedrooms"], 2)
        self.assertEqual(fields["property_type"].lower(), "apartment")
        self.assertIn("Dubai Marina", fields["preferred_location"])
        self.assertIsNotNone(fields["budget_max"])

    def test_result_never_leaks_key_material(self):
        result = analyse_enquiry(self.ENQUIRY, provider="offline")
        blob = repr(result).lower()
        self.assertNotIn("api_key", blob)
        self.assertNotIn("sk-", blob)

    def test_provider_status_is_boolean_only(self):
        status = provider_status()
        for key in ("openai", "groq", "offline"):
            self.assertIn(key, status)
        self.assertIsInstance(status["openai"], bool)
        self.assertIsInstance(status["groq"], bool)
        self.assertTrue(status["offline"])

    def test_missing_details_produce_clarification_questions(self):
        result = analyse_enquiry("I want a nice property somewhere soon please",
                                 provider="offline")
        self.assertTrue(result["missing_fields"])
        self.assertTrue(result["clarification_questions"])

    def test_unknown_provider_falls_back_to_a_real_provider(self):
        # An unrecognised provider name must fall through to the normal
        # chain (never crash). With no live keys reachable the chain must
        # end at the offline heuristic.
        from unittest import mock
        import services.ai_extract as ai
        with mock.patch.object(ai, "OPENAI_API_KEY", ""), \
                mock.patch.object(ai, "GROQ_API_KEY", ""):
            result = ai.analyse_enquiry(self.ENQUIRY, provider="does-not-exist")
        self.assertEqual(result["provider"], "offline-heuristic")
        self.assertIn("fields", result)

    def test_offline_never_raises_for_unusual_text(self):
        for text in ("✨✨✨✨✨✨✨✨✨✨✨", "1" * 500,
                     "!!! Looking !!! for $$$ anything ??? please"):
            result = analyse_enquiry(text, provider="offline")
            self.assertIn("fields", result)


if __name__ == "__main__":
    unittest.main()
