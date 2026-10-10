"""
tests/helpers.py
Shared test bootstrap + helpers for the auth / RBAC / CSRF test suites.

IMPORTANT — import this module FIRST in every test file, before importing
`app`. On first import it:
  1. copies the real crm.db into a disposable temp database,
  2. points `database.DB_PATH` at that copy (so the real database is never
     touched by tests),
  3. migrates the copy (additive tables/columns),
  4. imports the app + support modules.

It also exposes small helpers, e.g.
    client = helpers.client_for(["Sales/CRM"])
    helpers.post(client, "/properties/new", data={...})
    helpers.get(client, "/properties")
"""

import os
import secrets
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- point ALL database access at a disposable copy BEFORE importing app ---
DEBUG_DB = os.path.join(tempfile.mkdtemp(prefix="lyka_tests_"), "crm_copy.db")
if os.path.exists(os.path.join(ROOT, "crm.db")):
    shutil.copyfile(os.path.join(ROOT, "crm.db"), DEBUG_DB)

import database  # noqa: E402
database.DB_PATH = DEBUG_DB
database.init_db()
database.bootstrap_roles()

import app as app_module  # noqa: E402
import ai_assistant  # noqa: E402
import services.groq_service as groq_service  # noqa: E402
import services.pdf_exporter as pdf_module  # noqa: E402
import brd  # noqa: E402

_PASSWORD = "UnittestPass1!"


def make_user(username, password=_PASSWORD, roles=("Super Admin",),
              **fields):
    """Create a user in the disposable DB (unique username) and return the row."""
    if database.get_user_by_username(username):
        return database.get_user_by_username(username)
    from werkzeug.security import generate_password_hash
    user_id = database.create_user(
        username=username,
        password_hash=generate_password_hash(password),
        roles=list(roles),
        **fields,
    )
    return database.get_user_by_id(user_id)


def login(client, username, password=_PASSWORD):
    """Perform a real login (GET form → POST) against the given test client."""
    client.get("/login")
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    return client.post(
        "/login",
        data={"username": username, "password": password,
              "csrf_token": csrf},
        follow_redirects=False,
    )


def client_for(roles, username=None, password=_PASSWORD):
    """New test client already logged in as a user with the given roles."""
    username = username or f"ut_{roles[0].replace('/', '_').replace(' ', '_')}_{secrets.token_hex(2)}"
    make_user(username, password=password, roles=roles)
    client = app_module.app.test_client()
    resp = login(client, username, password)
    assert resp.status_code in (200, 302), f"login failed: {resp.status_code}"
    return client


def current_user(client):
    """User row for the logged-in test client (from its own session)."""
    with client.session_transaction() as sess:
        return database.get_user_by_id(sess.get("user_id"))


def ccsrf(client):
    """Return (and if needed create) the client session's CSRF token."""
    with client.session_transaction() as sess:
        if "csrf_token" not in sess or not sess["csrf_token"]:
            sess["csrf_token"] = secrets.token_hex(32)
        return sess["csrf_token"]


def get(client, path, **kw):
    return client.get(path, **kw)


def post(client, path, data=None, json=None, **kw):
    """POST with the session CSRF token auto-injected (form field or header)."""
    token = ccsrf(client)
    if json is not None:
        headers = dict(kw.pop("headers", {}) or {})
        headers.setdefault("X-CSRFToken", token)
        return client.post(path, json=json, headers=headers, **kw)
    payload = dict(data or {})
    payload.setdefault("csrf_token", token)
    return client.post(path, data=payload, **kw)