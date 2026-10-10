"""
tests/test_lead_rescoring.py
R1 — editing a lead through the legacy form must re-score the MERGED record,
so AI-extracted fields (purpose, property_type, amenities, timeline, min/max
budget) are preserved and the previously earned score does not silently drop.

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import database  # noqa: E402


def _analysed_lead_data():
    """A fully-populated AI-analysed lead (as saved by the analysis screen)."""
    return {
        "client_name": "UNITTEST Rescore Lead",
        "phone": "+971500000001",
        "email": "rescore@example.com",
        "budget": "1800000",
        "preferred_location": "Dubai Marina",
        "bedrooms_needed": "2",
        "needs_swimming_pool": "Yes",
        "needs_nearby_metro": "Yes",
        "status": "Analysed",
        "lead_source": "AI Analysis",
        "assigned_to": "",
        "next_follow_up": "",
        "last_contact": "",
        "notes": "Wants a marina view.",
        "lead_type": "buyer",
        "property_type": "Apartment",
        "budget_min": "1500000",
        "budget_max": "1800000",
        "currency": "AED",
        "purpose": "buy",
        "amenities": "Swimming pool, Gym",
        "timeline_days": "90",
        "timeline_label": "within 3 months",
        "raw_enquiry": "I want a 2-bed apartment in Dubai Marina.",
        "analysis_provider": "offline-heuristic",
        "analysed_at": "2026-10-10 12:00:00",
    }


def _legacy_edit_payload(lead, **overrides):
    """Exactly the fields templates/lead_form.html submits — nothing more."""
    payload = {
        "client_name": lead["client_name"],
        "phone": lead["phone"] or "",
        "email": lead["email"] or "",
        "budget": "" if lead["budget"] is None else str(int(lead["budget"])),
        "preferred_location": lead["preferred_location"] or "",
        "bedrooms_needed": ("" if lead["bedrooms_needed"] is None
                            else str(lead["bedrooms_needed"])),
        "needs_swimming_pool": lead["needs_swimming_pool"] or "No",
        "needs_nearby_metro": lead["needs_nearby_metro"] or "No",
        "status": lead["status"],
        "lead_source": lead["lead_source"] or "",
        "assigned_to": lead["assigned_to"] or "",
        "next_follow_up": lead["next_follow_up"] or "",
        "last_contact": lead["last_contact"] or "",
        "notes": lead["notes"] or "",
    }
    payload.update(overrides)
    return payload


class LeadRescoringTests(unittest.TestCase):
    def setUp(self):
        self.client = helpers.client_for(["Super Admin"])

    def _make_lead(self):
        lead_id = database.add_lead(_analysed_lead_data())
        self.addCleanup(database.delete_lead, lead_id)
        return lead_id

    def test_legacy_edit_preserves_ai_fields_and_score(self):
        lead_id = self._make_lead()
        before = database.get_lead(lead_id)

        r = helpers.post(self.client, f"/leads/{lead_id}/edit",
                         data=_legacy_edit_payload(before))
        self.assertEqual(r.status_code, 302)

        after = database.get_lead(lead_id)
        # AI fields the legacy form never renders must survive the edit ...
        self.assertEqual(after["purpose"], before["purpose"])
        self.assertEqual(after["property_type"], before["property_type"])
        self.assertEqual(after["lead_type"], before["lead_type"])
        self.assertEqual(after["amenities"], before["amenities"])
        self.assertEqual(after["timeline_days"], before["timeline_days"])
        self.assertEqual(after["budget_min"], before["budget_min"])
        self.assertEqual(after["budget_max"], before["budget_max"])
        self.assertEqual(after["raw_enquiry"], before["raw_enquiry"])
        self.assertEqual(after["analysis_provider"], before["analysis_provider"])
        self.assertEqual(after["analysed_at"], before["analysed_at"])
        # ... and the score is not recomputed from the incomplete form data.
        self.assertEqual(after["lead_score"], before["lead_score"])
        self.assertEqual(after["priority"], before["priority"])

    def test_relevant_change_still_re_scores(self):
        lead_id = self._make_lead()
        before = database.get_lead(lead_id)

        # Clearing the location genuinely changes the data -> 20 points drop.
        r = helpers.post(self.client, f"/leads/{lead_id}/edit",
                         data=_legacy_edit_payload(before, preferred_location=""))
        self.assertEqual(r.status_code, 302)

        after = database.get_lead(lead_id)
        self.assertEqual(after["preferred_location"], "")
        self.assertEqual(after["lead_score"], before["lead_score"] - 20)
        # The untouched AI fields are still preserved.
        self.assertEqual(after["purpose"], before["purpose"])
        self.assertEqual(after["amenities"], before["amenities"])


if __name__ == "__main__":
    unittest.main()
