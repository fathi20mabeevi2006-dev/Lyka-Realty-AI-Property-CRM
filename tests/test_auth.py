"""
tests/test_auth.py
Phase 2 — login / logout / account-status behaviour.

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import app_module, database  # noqa: E402


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.make_user("auth_admin")
        cls.client = app_module.app.test_client()

    def test_anonymous_access_redirects_to_login(self):
        for path in ("/", "/properties", "/leads", "/assistant", "/brd"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r.headers.get("Location", "").startswith("/login"))

    def test_api_anonymous_returns_json_401(self):
        r = self.client.get("/api/assistant")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.content_type, "application/json")

    def test_login_success_sets_session(self):
        client = app_module.app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            csrf = sess["csrf_token"]
        r = client.post("/login",
                        data={"username": "auth_admin",
                              "password": "UnittestPass1!",
                              "csrf_token": csrf})
        self.assertEqual(r.status_code, 302)
        with client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"),
                             database.get_user_by_username("auth_admin")["id"])
        # a protected page now renders
        self.assertEqual(client.get("/").status_code, 200)

    def test_login_wrong_password_rejected(self):
        client = app_module.app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            csrf = sess["csrf_token"]
        r = client.post("/login",
                        data={"username": "auth_admin",
                              "password": "WrongPass123!",
                              "csrf_token": csrf})
        self.assertEqual(r.status_code, 401)
        with client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_login_unknown_user_rejected(self):
        client = app_module.app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            csrf = sess["csrf_token"]
        r = client.post("/login",
                        data={"username": "nobody_user",
                              "password": "Whatever123!",
                              "csrf_token": csrf})
        self.assertEqual(r.status_code, 401)

    def test_disabled_account_cannot_login(self):
        user = helpers.make_user("disabled_user")
        database.set_user_status(user["id"], "Disabled")
        client = app_module.app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            csrf = sess["csrf_token"]
        r = client.post("/login",
                        data={"username": "disabled_user",
                              "password": "UnittestPass1!",
                              "csrf_token": csrf})
        # re-renders the login form with an error
        self.assertIn("not active", r.get_data(as_text=True).lower())
        with client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_disabled_session_force_logged_out(self):
        user = helpers.make_user("force_logout_user")
        client = helpers.client_for(["Super Admin"], username="force_logout_user")
        self.assertEqual(client.get("/").status_code, 200)
        database.set_user_status(user["id"], "Suspended")
        r = client.get("/")
        self.assertEqual(r.status_code, 302)  # kicked out
        self.assertTrue(r.headers.get("Location", "").startswith("/login"))

    def test_logout_clears_session(self):
        client = helpers.client_for(["Super Admin"], username="auth_admin")
        r = helpers.post(client, "/logout")
        self.assertEqual(r.status_code, 302)
        with client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))
        self.assertEqual(client.get("/").status_code, 302)


if __name__ == "__main__":
    unittest.main(verbosity=2)