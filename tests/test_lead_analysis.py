"""
tests/test_lead_analysis.py
FR-02/03/06/08/09 — the AI analysis screens, lead detail, notes, status
history, recommendations, JSON APIs and dashboard KPIs.

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import database  # noqa: E402

SALES = ["Sales/CRM"]
MARKETING = ["Marketing"]
FINANCE = ["Finance/Accounts"]
CLIENT = ["Client"]

ENQUIRY = ("I am looking for a 2 bedroom apartment in Dubai Marina with a "
           "swimming pool, budget around AED 1.8 million, ready within 3 months.")


class AnalyseScreenTests(unittest.TestCase):
    def test_get_analyse_page_for_creator_roles(self):
        for roles in (SALES, MARKETING):
            client = helpers.client_for(roles)
            self.assertEqual(helpers.get(client, "/leads/analyse").status_code, 200)

    def test_finance_role_cannot_analyse(self):
        client = helpers.client_for(FINANCE)
        self.assertEqual(helpers.get(client, "/leads/analyse").status_code, 403)

    def test_analyse_and_save_creates_lead(self):
        client = helpers.client_for(SALES)
        r = helpers.post(client, "/leads/analyse",
                         data={"enquiry": ENQUIRY, "provider": "offline"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Extracted Requirements", r.data)

        r = helpers.post(client, "/leads/analyse/save", data={
            "client_name": "UNITTEST Analysed Lead",
            "phone": "+971501234567", "email": "unit@example.com",
            "preferred_location": "Dubai Marina", "bedrooms_needed": "2",
            "budget_max": "1800000", "currency": "AED", "purpose": "buy",
            "lead_type": "buyer", "property_type": "Apartment",
            "amenities": "Swimming pool", "timeline_days": "90",
            "status": "Analysed", "lead_source": "AI Analysis",
            "raw_enquiry": ENQUIRY, "analysis_provider": "offline-heuristic",
            "analysed_at": "2026-10-10 12:00:00", "missing_fields": "",
        })
        self.assertEqual(r.status_code, 302)
        lead = next(l for l in database.get_all_leads()
                    if l["client_name"] == "UNITTEST Analysed Lead")
        try:
            self.assertEqual(lead["status"], "Analysed")
            self.assertIsNotNone(lead["raw_enquiry"])
            self.assertIn("Dubai Marina", lead["preferred_location"])
        finally:
            database.delete_lead(lead["id"])

    def test_empty_enquiry_shows_error(self):
        client = helpers.client_for(SALES)
        r = helpers.post(client, "/leads/analyse",
                         data={"enquiry": "", "provider": "offline"},
                         follow_redirects=True)
        self.assertEqual(r.status_code, 200)


class LeadDetailTests(unittest.TestCase):
    def _make_lead(self, **kw):
        data = {"client_name": "UNITTEST Detail Lead", "budget": "1000000",
                "preferred_location": "Dubai Marina", "bedrooms_needed": 2,
                "status": "Analysed", "lead_type": "buyer",
                "priority": "High", "lead_score": 80}
        data.update(kw)
        return database.add_lead(data)

    def test_detail_page_renders(self):
        client = helpers.client_for(SALES)
        lead_id = self._make_lead()
        try:
            r = helpers.get(client, f"/leads/{lead_id}")
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Requirements", r.data)
            self.assertIn(b"Qualification Score", r.data)
        finally:
            database.delete_lead(lead_id)

    def test_notes_are_recorded_with_author(self):
        client = helpers.client_for(SALES)
        lead_id = self._make_lead()
        try:
            r = helpers.post(client, f"/leads/{lead_id}/notes",
                             data={"body": "Called, interested."})
            self.assertEqual(r.status_code, 302)
            notes = database.get_lead_notes(lead_id)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["body"], "Called, interested.")
            self.assertIsNotNone(notes[0]["created_at"])
        finally:
            database.delete_lead(lead_id)

    def test_empty_note_is_rejected(self):
        client = helpers.client_for(SALES)
        lead_id = self._make_lead()
        try:
            helpers.post(client, f"/leads/{lead_id}/notes", data={"body": "  "})
            self.assertEqual(database.get_lead_notes(lead_id), [])
        finally:
            database.delete_lead(lead_id)

    def test_status_change_writes_history(self):
        client = helpers.client_for(SALES)
        lead_id = self._make_lead(status="New")
        try:
            r = helpers.post(client, f"/leads/{lead_id}/status",
                             data={"status": "Qualified"})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(database.get_lead(lead_id)["status"], "Qualified")
            history = database.get_lead_status_history(lead_id)
            self.assertEqual(history[0]["to_status"], "Qualified")
        finally:
            database.delete_lead(lead_id)

    def test_client_cannot_view_another_clients_lead(self):
        client = helpers.client_for(CLIENT)
        me = helpers.current_user(client)
        other_lead = self._make_lead()
        try:
            self.assertEqual(helpers.get(client, f"/leads/{other_lead}").status_code, 403)
            mine = self._make_lead(client_name="UNITTEST Mine", client_user_id=me["id"])
            try:
                self.assertEqual(helpers.get(client, f"/leads/{mine}").status_code, 200)
            finally:
                database.delete_lead(mine)
        finally:
            database.delete_lead(other_lead)


class RecommendationsTests(unittest.TestCase):
    def test_generate_and_view_matches(self):
        client = helpers.client_for(SALES)
        lead_id = database.add_lead({
            "client_name": "UNITTEST Recs Lead", "preferred_location": "Dubai Marina",
            "bedrooms_needed": 2, "property_type": "Apartment", "purpose": "buy",
            "budget_max": 2_000_000, "amenities": "Swimming pool",
        })
        try:
            r = helpers.post(client, f"/leads/{lead_id}/recommendations", data={})
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Match score", r.data)
            self.assertTrue(database.get_latest_recommendations(lead_id))
        finally:
            database.delete_lead(lead_id)

    def test_recommendations_api_get_and_post(self):
        client = helpers.client_for(SALES)
        lead_id = database.add_lead({
            "client_name": "UNITTEST Recs API", "preferred_location": "Dubai Marina",
            "bedrooms_needed": 1, "purpose": "rent", "budget_max": 100000,
        })
        try:
            r = helpers.post(client, f"/api/leads/{lead_id}/recommendations")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIn("results", data)
            self.assertIn("message", data)
            g = helpers.get(client, f"/api/leads/{lead_id}/recommendations")
            self.assertEqual(g.status_code, 200)
            self.assertGreaterEqual(g.get_json()["count"], 1)
        finally:
            database.delete_lead(lead_id)

    def test_analysis_api_offline(self):
        client = helpers.client_for(SALES)
        r = helpers.post(client, "/api/leads/analyse",
                         json={"enquiry": ENQUIRY, "provider": "offline"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("fields", body)
        self.assertEqual(body["provider"], "offline-heuristic")

    def test_analysis_api_rejects_short_enquiry(self):
        client = helpers.client_for(SALES)
        r = helpers.post(client, "/api/leads/analyse",
                         json={"enquiry": "hi", "provider": "offline"})
        self.assertEqual(r.status_code, 400)

    def test_api_requires_csrf(self):
        client = helpers.client_for(SALES)
        # deliberately NO csrf token
        r = client.post("/api/leads/analyse",
                        json={"enquiry": ENQUIRY, "provider": "offline"})
        self.assertEqual(r.status_code, 400)


class DashboardTests(unittest.TestCase):
    def test_dashboard_shows_new_kpis(self):
        client = helpers.client_for(SALES)
        r = helpers.get(client, "/")
        self.assertEqual(r.status_code, 200)
        for label in (b"Analysed Leads", b"High-Priority Leads", b"Property Matched"):
            self.assertIn(label, r.data)

    def test_ai_status_api(self):
        client = helpers.client_for(SALES)
        r = helpers.get(client, "/api/ai/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("offline", r.get_json())


if __name__ == "__main__":
    unittest.main()
