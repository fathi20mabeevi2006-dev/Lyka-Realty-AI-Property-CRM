"""
tests/test_business.py
Phase 3 tests for the Business Analysis module.

Run from the project root:
    python -m unittest discover -s tests -v

Every test runs against a DISPOSABLE COPY of crm.db, so the real database is
never modified.
"""

import os
import sys
import unittest

import helpers  # noqa: E402  (import FIRST: copies + migrates a throwaway DB)
from helpers import app_module, database, groq_service  # noqa: E402


class BusinessModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.make_user("business_admin")
        cls.client = helpers.client_for(["Super Admin"], username="business_admin")
        groq_service.GROQ_API_KEY = ""

    # ---------------------------------------------------------------- routes
    def test_phase3_pages_render(self):
        for path in ("/business", "/business/new", "/requirements",
                     "/requirements/new", "/gap-analysis"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    # ------------------------------------------------- tables / migration
    def test_phase3_tables_and_columns_exist(self):
        conn = database.get_connection()
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("business_analysis", tables)
            self.assertIn("requirements", tables)
            b_cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(business_analysis)")}
            self.assertIn("category", b_cols)
            self.assertIn("source_type", b_cols)
            self.assertIn("status", b_cols)
            self.assertIn("created_by", b_cols)
            self.assertIn("updated_at", b_cols)
            r_cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(requirements)")}
            for col in ("req_type", "priority", "status", "owner",
                        "current_state", "desired_state", "gap_notes"):
                self.assertIn(col, r_cols)
        finally:
            conn.close()

    # ------------------------------------------------------------ business CRUD
    def test_business_crud_round_trip(self):
        eid = database.add_business_entry({
            "category": "Target Customers",
            "title": "UNITTEST Note Alpha",
            "details": "Target mid-budget buyers in Dubai Marina.",
            "source_type": "Fact",
            "status": "Approved",
            "created_by": "local",
        })
        try:
            entry = database.get_business_entry(eid)
            self.assertEqual(entry["title"], "UNITTEST Note Alpha")
            self.assertEqual(entry["category"], "Target Customers")
            self.assertEqual(entry["source_type"], "Fact")
            self.assertEqual(entry["status"], "Approved")
            self.assertEqual(entry["created_by"], "local")
            self.assertIsNotNone(entry["created_at"])

            database.update_business_entry(eid, {
                "category": "Objectives",
                "title": "UNITTEST Note Alpha",
                "details": "Updated details.",
                "source_type": "Recommendation",
                "status": "Reviewed",
                "created_by": "local",
            })
            updated = database.get_business_entry(eid)
            self.assertEqual(updated["category"], "Objectives")
            self.assertEqual(updated["source_type"], "Recommendation")
            self.assertEqual(updated["status"], "Reviewed")
            self.assertIsNotNone(updated["updated_at"])
        finally:
            database.delete_business_entry(eid)
        self.assertIsNone(database.get_business_entry(eid))

    def test_business_whitelist_validation(self):
        eid = database.add_business_entry({
            "category": "Not-A-Category",
            "title": "UNITTEST Whitelist",
            "source_type": "Rumour",
            "status": "Blocked",
        })
        try:
            entry = database.get_business_entry(eid)
            self.assertEqual(entry["category"], "Other")
            self.assertEqual(entry["source_type"], "Fact")
            self.assertEqual(entry["status"], "Draft")
            self.assertEqual(entry["created_by"], "local")
        finally:
            database.delete_business_entry(eid)

    def test_business_title_required(self):
        with self.assertRaises(ValueError):
            database.add_business_entry({"title": "   "})

    def test_business_filters(self):
        eid = database.add_business_entry({
            "category": "Objectives",
            "title": "UNITTEST Filterable Note",
            "details": "Grow portfolio by 20% this year.",
            "source_type": "Assumption",
            "status": "Draft",
        })
        try:
            titles = lambda kw: [e["title"] for e in kw]
            self.assertIn("UNITTEST Filterable Note", titles(
                database.get_all_business_entries(category="Objectives")))
            self.assertIn("UNITTEST Filterable Note", titles(
                database.get_all_business_entries(source_type="Assumption")))
            self.assertNotIn("UNITTEST Filterable Note", titles(
                database.get_all_business_entries(status="Approved")))
            self.assertIn("UNITTEST Filterable Note", titles(
                database.get_all_business_entries(q="filterable note")))
            self.assertNotIn("UNITTEST Filterable Note", titles(
                database.get_all_business_entries(q="nonexistent-title-xyz")))
        finally:
            database.delete_business_entry(eid)

    # ------------------------------------------------------- route round trips
    def test_business_page_create_edit_delete_via_routes(self):
        r = helpers.post(
            self.client, "/business/new",
            data={"title": "UNITTEST Via Route", "category": "Challenges",
                  "details": "Created through the web form.",
                  "source_type": "Fact", "status": "Draft", "created_by": "local"},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("UNITTEST Via Route", r.get_data(as_text=True))

        entry = next(e for e in database.get_all_business_entries()
                     if e["title"] == "UNITTEST Via Route")
        try:
            r = self.client.get(f"/business/{entry['id']}/edit")
            self.assertEqual(r.status_code, 200)
            r = helpers.post(
                self.client, f"/business/{entry['id']}/edit",
                data={"title": "UNITTEST Via Route Edited", "category": "Challenges",
                      "details": "Edited.",
                      "source_type": "Recommendation", "status": "Approved",
                      "created_by": "local"},
                follow_redirects=True,
            )
            self.assertIn("UNITTEST Via Route Edited",
                          r.get_data(as_text=True))
            self.assertEqual(
                database.get_business_entry(entry["id"])["status"], "Approved")
        finally:
            database.delete_business_entry(entry["id"])

    def test_business_missing_entry_redirects(self):
        r = self.client.get("/business/999999/edit")
        self.assertEqual(r.status_code, 302)


if __name__ == "__main__":
    unittest.main(verbosity=2)