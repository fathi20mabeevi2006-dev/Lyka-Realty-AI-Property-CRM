"""
tests/test_phase25.py
Phase 2.5 regression tests.

Run from the project root:
    python -m unittest discover -s tests -v

Every test runs against a DISPOSABLE COPY of crm.db, so the real database is
never modified. This suite is data-count agnostic (it works with 18 rows or
6,514 rows).
"""

import unittest

import helpers  # noqa: E402  (import FIRST: copies + migrates a throwaway DB)
from helpers import ai_assistant, app_module, database, groq_service  # noqa: E402


class Phase25Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.make_user("phase25_admin")
        cls.client = helpers.client_for(["Super Admin"], username="phase25_admin")
        # Force the offline path so tests never depend on a live API key.
        groq_service.GROQ_API_KEY = ""

    # ---------------------------------------------------------------- routes
    def test_pages_render(self):
        for path in ("/", "/properties", "/properties/new", "/leads",
                     "/leads/new", "/assistant"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_currency_global_rendered(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(app_module.CURRENCY, html)

    # --------------------------------------------------- assistant (offline)
    def test_assistant_dashboard_stats(self):
        reply = helpers.post(
            self.client, "/api/assistant", json={"message": "Dashboard stats"}
        ).get_json()["reply"]
        self.assertIn("Properties:", reply)
        self.assertIn("Available:", reply)

    def test_assistant_leads_count(self):
        reply = ai_assistant.answer_question("how many leads")
        expected = database.get_dashboard_stats()["total_leads"]
        self.assertIn(str(expected), reply)

    def test_assistant_location_search_uses_real_data(self):
        properties = database.get_all_properties()
        if not properties:
            self.skipTest("no properties in test DB")
        location = properties[0]["location"].split(",")[0].strip()
        reply = ai_assistant.answer_question(f"show me properties in {location}")
        self.assertIn("Found", reply)

    def test_grounding_context_excludes_contacts(self):
        leads = database.get_all_leads()
        context = ai_assistant.grounding_context("dashboard stats")
        for lead in leads:
            if lead.get("phone"):
                self.assertNotIn(lead["phone"], context)
            if lead.get("email"):
                self.assertNotIn(lead["email"], context)

    # ------------------------------------------------ CRUD + new columns
    def test_property_type_and_size_round_trip(self):
        pid = database.add_property({
            "name": "UNITTEST Property Alpha", "location": "Dubai Marina",
            "price": "1000000", "bedrooms": "2", "bathrooms": "2",
            "floor_number": "3", "property_view": "Sea View",
            "has_swimming_pool": "Yes", "nearby_metro": "No",
            "status": "Available", "property_type": "Apartment",
            "property_size": "123.45",
        })
        prop = database.get_property(pid)
        self.assertEqual(prop["property_type"], "Apartment")
        self.assertAlmostEqual(float(prop["property_size"]), 123.45)

        database.update_property(pid, {
            "name": "UNITTEST Property Alpha", "location": "Dubai Marina",
            "price": "1000000", "bedrooms": "2", "bathrooms": "2",
            "floor_number": "3", "property_view": "Sea View",
            "has_swimming_pool": "Yes", "nearby_metro": "No",
            "status": "Sold", "property_type": "Apartment",
            "property_size": "123.45",
        })
        updated = database.get_property(pid)
        self.assertEqual(updated["status"], "Sold")
        self.assertIsNotNone(updated["updated_at"])
        database.delete_property(pid)

    def test_server_side_filter_matches_name(self):
        pid = database.add_property({
            "name": "UNITTEST UniqueName Zeta", "location": "Testville",
            "price": "500000", "bedrooms": "1", "bathrooms": "1",
            "status": "Available",
        })
        try:
            html = self.client.get(
                "/properties?q=UNITTEST%20UniqueName%20Zeta"
            ).get_data(as_text=True)
            self.assertIn("UNITTEST UniqueName Zeta", html)
        finally:
            database.delete_property(pid)

    def test_migration_adds_expected_columns(self):
        cols = {r[1] for r in database.get_connection().execute(
            "PRAGMA table_info(properties)")}
        self.assertIn("property_type", cols)
        self.assertIn("property_size", cols)
        self.assertIn("updated_at", cols)
        lead_cols = {r[1] for r in database.get_connection().execute(
            "PRAGMA table_info(leads)")}
        self.assertIn("updated_at", lead_cols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
