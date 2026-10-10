"""
tests/test_requirements.py
Phase 3 tests for the Requirements and Gap Analysis modules.

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


class RequirementsModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.make_user("req_admin")
        cls.client = helpers.client_for(["Super Admin"], username="req_admin")
        groq_service.GROQ_API_KEY = ""

    def _add_req(self, title, **overrides):
        data = {
            "title": title,
            "req_type": "Functional",
            "category": "Dashboard",
            "priority": "Medium",
            "status": "Draft",
            "owner": "Sales",
        }
        data.update(overrides)
        return database.add_requirement(data)

    # ------------------------------------------------------------ CRUD
    def test_requirement_crud_round_trip(self):
        rid = self._add_req(
            "UNITTEST Req Alpha",
            description="Full detail.",
            problem="Leads are tracked in a spreadsheet.",
            proposed_solution="A central CRM for all leads.",
            req_type="Functional", category="Leads & Clients",
            priority="High", status="Approved", owner="Sales team",
            acceptance_criteria="All leads visible with scoring.",
            dependencies="Import from spreadsheet.",
            risks="Data loss during import.",
            current_state="Manual spreadsheet.",
            desired_state="Automated CRM.",
            gap_notes="Automation layer missing.",
        )
        try:
            r = database.get_requirement(rid)
            self.assertEqual(r["title"], "UNITTEST Req Alpha")
            self.assertEqual(r["category"], "Leads & Clients")
            self.assertEqual(r["priority"], "High")
            self.assertEqual(r["status"], "Approved")
            self.assertEqual(r["owner"], "Sales team")
            self.assertEqual(r["acceptance_criteria"],
                             "All leads visible with scoring.")
            self.assertEqual(r["current_state"], "Manual spreadsheet.")
            self.assertEqual(r["desired_state"], "Automated CRM.")
            self.assertIsNotNone(r["created_at"])

            database.update_requirement(rid, {
                "title": "UNITTEST Req Alpha",
                "problem": "Updated problem.",
                "proposed_solution": "Updated solution.",
                "req_type": "Non-Functional",
                "category": "Security & Privacy",
                "priority": "Low",
                "status": "In Progress",
                "owner": "IT",
                "current_state": "Manual spreadsheet.",
                "desired_state": "Automated CRM.",
                "gap_notes": "",
            })
            updated = database.get_requirement(rid)
            self.assertEqual(updated["req_type"], "Non-Functional")
            self.assertEqual(updated["category"], "Security & Privacy")
            self.assertEqual(updated["priority"], "Low")
            self.assertEqual(updated["status"], "In Progress")
            self.assertEqual(updated["owner"], "IT")
            self.assertIsNotNone(updated["updated_at"])
        finally:
            database.delete_requirement(rid)
        self.assertIsNone(database.get_requirement(rid))

    def test_requirement_whitelist_validation(self):
        rid = self._add_req(
            "UNITTEST Whitelist Req",
            req_type="Bogus", category="Nope", priority="Urgent", status="Blocked",
        )
        try:
            r = database.get_requirement(rid)
            self.assertEqual(r["req_type"], "Functional")
            self.assertEqual(r["category"], "Other")
            self.assertEqual(r["priority"], "Medium")
            self.assertEqual(r["status"], "Draft")
            self.assertEqual(r["created_by"], "local")
        finally:
            database.delete_requirement(rid)

    def test_requirement_title_required(self):
        with self.assertRaises(ValueError):
            database.add_requirement({"title": ""})

    def test_requirement_filters(self):
        rid = self._add_req(
            "UNITTEST Filterable Req",
            req_type="Non-Functional", category="Reporting",
            priority="High", status="In Progress", owner="Ops",
        )
        try:
            titles = lambda kw: [r["title"] for r in kw]
            self.assertIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(req_type="Non-Functional")))
            self.assertIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(priority="High")))
            self.assertIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(category="Reporting")))
            self.assertNotIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(status="Done")))
            self.assertIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(q="filterable req")))
            self.assertIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(q="ops")))  # matches the owner
            self.assertNotIn("UNITTEST Filterable Req", titles(
                database.get_all_requirements(q="zzz-no-match")))
        finally:
            database.delete_requirement(rid)

    # --------------------------------------------------------- gap derivation
    def test_gap_derivation_rules(self):
        a = self._add_req("UNITTEST Gap True",
                          current_state="Manual", desired_state="Automated")
        b = self._add_req("UNITTEST Gap False",
                          current_state="Same", desired_state="Same")
        c = self._add_req("UNITTEST Gap Partial",
                          current_state="Manual", desired_state="")
        d = self._add_req("UNITTEST Gap Notes",
                          current_state="Manual", desired_state="Manual",
                          gap_notes="Still needs automation.")
        try:
            view = database.get_gap_analysis()
            by_title = {i["title"]: i["has_gap"] for i in view["items"]}
            self.assertIs(by_title["UNITTEST Gap True"], True)
            self.assertIs(by_title["UNITTEST Gap False"], False)
            self.assertIs(by_title["UNITTEST Gap Partial"], False)
            self.assertIs(by_title["UNITTEST Gap Notes"], True)
            # gap_count must always equal the number of flagged items,
            # regardless of how many records already exist in the copy.
            self.assertEqual(
                view["gap_count"],
                sum(1 for i in view["items"] if i["has_gap"]),
            )
        finally:
            for rid in (a, b, c, d):
                database.delete_requirement(rid)

    def test_gap_analysis_sorted_by_priority(self):
        low = self._add_req("UNITTEST Gap Low", priority="Low",
                            current_state="A", desired_state="B")
        high = self._add_req("UNITTEST Gap High", priority="High",
                             current_state="A", desired_state="B")
        try:
            view = database.get_gap_analysis()
            self.assertEqual(view["items"][0]["title"], "UNITTEST Gap High")
        finally:
            database.delete_requirement(low)
            database.delete_requirement(high)

    # ----------------------------------------------------- routes / pages
    def test_requirements_create_edit_delete_via_routes(self):
        r = helpers.post(
            self.client, "/requirements/new",
            data={"title": "UNITTEST Req Via Route",
                  "problem": "No central view.",
                  "proposed_solution": "Build a CRM.",
                  "req_type": "Functional", "category": "Dashboard",
                  "priority": "High", "status": "Draft", "owner": "Sales",
                  "current_state": "Manual", "desired_state": "Automated"},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("UNITTEST Req Via Route", html)
        self.assertIn("Gap", html)  # auto-flagged gap badge on the list page

        req = next(x for x in database.get_all_requirements()
                   if x["title"] == "UNITTEST Req Via Route")
        try:
            r = self.client.get(f"/requirements/{req['id']}/edit")
            self.assertEqual(r.status_code, 200)
            r = helpers.post(
                self.client, f"/requirements/{req['id']}/edit",
                data={"title": "UNITTEST Req Edited",
                      "req_type": "Functional", "category": "Dashboard",
                      "priority": "Low", "status": "Done", "owner": "Sales"},
                follow_redirects=True,
            )
            self.assertIn("UNITTEST Req Edited", r.get_data(as_text=True))
            self.assertEqual(
                database.get_requirement(req["id"])["status"], "Done")
        finally:
            database.delete_requirement(req["id"])

    def test_gap_page_only_gaps_filter(self):
        gap = self._add_req("UNITTEST Show Gap",
                            current_state="Manual", desired_state="Automated")
        nogap = self._add_req("UNITTEST Hide NoGap",
                              current_state="Same", desired_state="Same")
        try:
            html = self.client.get(
                "/gap-analysis?only_gaps=1").get_data(as_text=True)
            self.assertIn("UNITTEST Show Gap", html)
            self.assertNotIn("UNITTEST Hide NoGap", html)

            full = self.client.get(
                "/gap-analysis").get_data(as_text=True)
            self.assertIn("UNITTEST Hide NoGap", full)
            self.assertIn("Gap identified", full)
        finally:
            database.delete_requirement(gap)
            database.delete_requirement(nogap)

    def test_requirement_missing_entry_redirects(self):
        r = self.client.get("/requirements/999999/edit")
        self.assertEqual(r.status_code, 302)


if __name__ == "__main__":
    unittest.main(verbosity=2)