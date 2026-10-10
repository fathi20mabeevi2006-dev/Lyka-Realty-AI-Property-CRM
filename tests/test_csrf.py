"""
tests/test_csrf.py
Phase 2 — CSRF token enforcement on every state-changing request.

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import app_module, database  # noqa: E402


class CSRFProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.make_user("csrf_admin")

    def _admin_client(self):
        return helpers.client_for(["Super Admin"], username="csrf_admin")

    def test_form_post_without_token_is_rejected(self):
        client = self._admin_client()
        r = client.post("/business/new", data={
            "title": "UNITTEST NoCSRF", "category": "Other", "details": "x",
            "source_type": "Fact", "status": "Draft",
        })
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("UNITTEST NoCSRF",
                         [e["title"] for e in database.get_all_business_entries()])

    def test_form_post_with_wrong_token_is_rejected(self):
        client = self._admin_client()
        r = client.post("/business/new", data={
            "title": "UNITTEST BadCSRF", "category": "Other", "details": "x",
            "source_type": "Fact", "status": "Draft",
            "csrf_token": "a" * 64,
        })
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("UNITTEST BadCSRF",
                         [e["title"] for e in database.get_all_business_entries()])

    def test_form_post_with_valid_token_succeeds(self):
        client = self._admin_client()
        r = helpers.post(client, "/business/new", data={
            "title": "UNITTEST GoodCSRF", "category": "Other", "details": "x",
            "source_type": "Fact", "status": "Draft",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("UNITTEST GoodCSRF",
                      [e["title"] for e in database.get_all_business_entries()])

    def test_api_post_without_token_returns_400_json(self):
        client = self._admin_client()
        r = client.post("/api/assistant", json={"message": "hi"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.content_type, "application/json")
        self.assertIn("error", r.get_json())

    def test_api_post_with_valid_header_succeeds(self):
        client = self._admin_client()
        r = helpers.post(client, "/api/assistant", json={"message": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("reply", r.get_json())

    def test_login_page_requires_token_but_get_works(self):
        client = app_module.app.test_client()
        self.assertEqual(client.get("/login").status_code, 200)
        r = client.post("/login", data={"username": "csrf_admin",
                                        "password": "UnittestPass1!"})
        self.assertEqual(r.status_code, 302)  # rejected (no csrf field)
        with client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))


if __name__ == "__main__":
    unittest.main(verbosity=2)