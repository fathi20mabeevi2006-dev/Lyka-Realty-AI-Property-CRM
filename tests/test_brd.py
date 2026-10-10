"""
tests/test_brd.py
Phase 4 tests for the BRD (Business Requirements Document) generator.

Run from the project root:
    python -m unittest discover -s tests -v

Every test runs against a DISPOSABLE COPY of crm.db, so the real database is
never modified. The real crm.db may contain user test records; assertions
here use unique "UNITTEST BRD ..." titles and never depend on real data.
"""

import re
import unittest

import helpers  # noqa: E402  (import FIRST: copies + migrates a throwaway DB)
from helpers import app_module, brd, database, pdf_module  # noqa: E402


class BRDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = helpers.client_for(["Super Admin"], username="brd_admin")

    def _note(self, title, category="Other", details="Details here.",
              source_type="Fact", status="Draft"):
        return database.add_business_entry({
            "category": category, "title": title, "details": details,
            "source_type": source_type, "status": status, "created_by": "local",
        })

    def _req(self, title, **overrides):
        data = {
            "title": title,
            "req_type": "Functional", "category": "Dashboard",
            "priority": "Medium", "status": "Draft", "owner": "Tester",
        }
        data.update(overrides)
        return database.add_requirement(data)

    # ---------------------------------------------------------------- render
    def test_preview_page_renders(self):
        r = self.client.get("/brd")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Business Requirements Document", html)
        self.assertIn("Current State", html)
        self.assertIn("Missing Information", html)

    # ------------------------------------------------------------ live facts
    def test_current_state_uses_real_stats_with_timestamp(self):
        doc = brd.build_brd()
        stats = database.get_dashboard_stats()
        by_label = {i["label"]: i["value"] for i in doc["current_state"]["facts"]}
        self.assertEqual(by_label["Total properties"], f"{stats['total_properties']:,}")
        self.assertEqual(by_label["Total property leads"], f"{stats['total_leads']:,}")
        self.assertIn("verified directly from the CRM database",
                      doc["current_state"]["stats_label"])
        self.assertRegex(
            doc["current_state"]["stats_label"],
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}",
        )
        # portfolio explanation is always present and honest
        portfolio = next(i for i in doc["current_state"]["facts"]
                         if i["label"].startswith("Portfolio value"))
        self.assertIn("lower-bound", portfolio["note"])
        self.assertIn("priced", portfolio["note"])

    # ------------------------------------- facts / assumptions / recommendations
    def test_source_types_split_correctly(self):
        self._note("UNITTEST BRD Fact A", source_type="Fact")
        self._note("UNITTEST BRD Fact B", source_type="Fact")
        self._note("UNITTEST BRD Assumption A", source_type="Assumption")
        self._note("UNITTEST BRD Rec A", source_type="Recommendation")
        try:
            doc = brd.build_brd()
            self.assertEqual(
                len([e for e in doc["fact_base"] if e["title"].startswith("UNITTEST BRD")]), 2)
            self.assertEqual(
                len([e for e in doc["assumptions"] if e["title"].startswith("UNITTEST BRD")]), 1)
            self.assertEqual(
                len([e for e in doc["recommendations"] if e["title"].startswith("UNITTEST BRD")]), 1)
        finally:
            for e in database.get_all_business_entries():
                if e["title"].startswith("UNITTEST BRD"):
                    database.delete_business_entry(e["id"])

    def test_company_profile_and_objectives_grouped(self):
        self._note("UNITTEST BRD Profile", category="Company Profile")
        self._note("UNITTEST BRD Objective", category="Objectives")
        try:
            doc = brd.build_brd()
            self.assertEqual(
                len([e for e in doc["company_profile"] if e["title"] == "UNITTEST BRD Profile"]), 1)
            self.assertEqual(
                len([e for e in doc["objectives"] if e["title"] == "UNITTEST BRD Objective"]), 1)
        finally:
            for e in database.get_all_business_entries():
                if e["title"].startswith("UNITTEST BRD"):
                    database.delete_business_entry(e["id"])

    # -------------------------------------------------- requirements content
    def test_problems_solutions_priorities_acceptance(self):
        rid = self._req(
            "UNITTEST BRD Payload Req", priority="High", status="Approved",
            problem="Buyers search manually.",
            proposed_solution="Add a price filter.",
            acceptance_criteria="Buyers can filter by price range.",
        )
        try:
            doc = brd.build_brd()
            prob_titles = {p["title"] for p in doc["problems"]}
            sol_titles = {s["title"] for s in doc["solutions"]}
            self.assertIn("UNITTEST BRD Payload Req", prob_titles)
            self.assertIn("UNITTEST BRD Payload Req", sol_titles)

            row = next(r for r in doc["functional"]
                       if r["title"] == "UNITTEST BRD Payload Req")
            self.assertEqual(row["priority"], "High")
            self.assertEqual(row["status"], "Approved")
            self.assertEqual(row["problem"], "Buyers search manually.")
            self.assertEqual(row["acceptance_criteria"],
                             "Buyers can filter by price range.")
        finally:
            database.delete_requirement(rid)

    def test_requirements_sorted_by_priority(self):
        low = self._req("UNITTEST BRD Low Req", priority="Low")
        high = self._req("UNITTEST BRD High Req", priority="High")
        try:
            doc = brd.build_brd()
            titles = [r["title"] for r in doc["functional"]
                      if r["title"].startswith("UNITTEST BRD")]
            self.assertLess(titles.index("UNITTEST BRD High Req"),
                            titles.index("UNITTEST BRD Low Req"))
        finally:
            database.delete_requirement(low)
            database.delete_requirement(high)

    # --------------------------------------------------------- honesty rules
    def test_missing_information_honest(self):
        rid = self._req("UNITTEST BRD Bare Req")  # title only
        try:
            doc = brd.build_brd()
            # The bare requirement must NOT appear in problems or solutions.
            self.assertNotIn(
                "UNITTEST BRD Bare Req", {p["title"] for p in doc["problems"]})
            self.assertNotIn(
                "UNITTEST BRD Bare Req", {s["title"] for s in doc["solutions"]})
            # ...and it IS reported as missing, never invented.
            self.assertTrue(any("UNITTEST BRD Bare Req" in m for m in doc["missing"]))
        finally:
            database.delete_requirement(rid)

    def test_gap_summary_matches_db(self):
        a = self._req("UNITTEST BRD Gap Req", current_state="Manual",
                      desired_state="Automated", priority="High")
        b = self._req("UNITTEST BRD No-Gap Req", current_state="Same",
                      desired_state="Same")
        try:
            doc = brd.build_brd()
            db_view = database.get_gap_analysis()
            self.assertEqual(doc["gap_summary"]["gap_count"], db_view["gap_count"])
            self.assertEqual(doc["gap_summary"]["total"], db_view["total"])
            self.assertIn(
                "UNITTEST BRD Gap Req", {i["title"] for i in doc["gap_summary"]["gaps"]})
        finally:
            database.delete_requirement(a)
            database.delete_requirement(b)

    # ---------------------------------------------------------------- PDF
    def test_pdf_bytes_are_valid_when_library_present(self):
        if not pdf_module.pdf_available():
            self.skipTest("fpdf2 not installed in this environment")
        doc = brd.build_brd()
        pdf_bytes = pdf_module.export_brd_pdf(doc)
        self.assertGreater(len(pdf_bytes), 500)
        self.assertEqual(pdf_bytes[:4], b"%PDF")

    def test_export_endpoint_downloads_pdf(self):
        if not pdf_module.pdf_available():
            self.skipTest("fpdf2 not installed in this environment")
        r = self.client.get("/brd/export")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        disposition = r.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disposition)
        self.assertRegex(disposition, r"BRD_LykaRealty_\d{8}_\d{6}\.pdf")

    def test_export_degrades_gracefully_when_library_missing(self):
        original = pdf_module.PDF_AVAILABLE
        pdf_module.PDF_AVAILABLE = False
        try:
            r = self.client.get("/brd/export")
            self.assertEqual(r.status_code, 302)  # redirect back to /brd
            self.assertTrue(r.headers.get("Location", "").endswith("/brd"))
        finally:
            pdf_module.PDF_AVAILABLE = original


if __name__ == "__main__":
    unittest.main(verbosity=2)