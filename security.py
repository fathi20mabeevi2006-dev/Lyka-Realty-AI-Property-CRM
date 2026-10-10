"""
security.py
Phase 2 — authentication & role-based access control (RBAC) foundation.

Responsibilities
----------------
* Permission matrix for the eight agreed Lyka Realty roles.
* Login guards / permission checks (used by app.py before_request + routes).
* Session-safe helpers (cookie flags are set in app.py from config).
* CSRF token issue + validation (no external dependency).
* One-place audit helper (writes via database.add_audit_log).
* Small in-memory rate limiter for the AI assistant endpoint.

Design rules
------------
* Permissions are enforced in the BACKEND — templates only hide links.
* A user may hold several roles; effective permission = union of roles.
* "Client" may reach only records explicitly linked to their account; the
  row-level scoping is applied in the routes (see leads_scope / client_scope).
* This module must NEVER import app.py (only flask + database) to avoid
  circular imports.
"""

import functools
import secrets
import threading
import time

from flask import flash, g, jsonify, redirect, render_template, request, session, url_for

from database import (
    get_user_by_id,
    get_user_roles,
    add_audit_log as _write_audit,
)

# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #

ROLE_SUPER_ADMIN = "Super Admin"
ROLE_COMPANY_ADMIN = "Company Admin"
ROLE_SALES = "Sales/CRM"
ROLE_MARKETING = "Marketing"
ROLE_FINANCE = "Finance/Accounts"
ROLE_HR = "HR/Employees"
ROLE_PROPERTY = "Property/Operations"
ROLE_CLIENT = "Client"

ALL_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COMPANY_ADMIN,
    ROLE_SALES,
    ROLE_MARKETING,
    ROLE_FINANCE,
    ROLE_HR,
    ROLE_PROPERTY,
    ROLE_CLIENT,
)

ROLE_DESCRIPTIONS = {
    ROLE_SUPER_ADMIN: "Full system access including user, role and audit management.",
    ROLE_COMPANY_ADMIN: "Management visibility, operational control and approvals.",
    ROLE_SALES: "Leads, pipeline, follow-ups and property viewing.",
    ROLE_MARKETING: "Campaigns and lead-generation source tracking.",
    ROLE_FINANCE: "Financial records: invoices, receipts, commissions.",
    ROLE_HR: "Employee and internal workflows.",
    ROLE_PROPERTY: "Property listings and maintenance operations.",
    ROLE_CLIENT: "External client portal; own records only.",
}

# --------------------------------------------------------------------------- #
# Permissions (string identifiers used across routes, templates and tests)
# --------------------------------------------------------------------------- #

PERM_DASHBOARD = "dashboard.view"
PERM_PROPERTIES_VIEW = "properties.view"
PERM_PROPERTIES_CREATE = "properties.create"
PERM_PROPERTIES_EDIT = "properties.edit"
PERM_PROPERTIES_DELETE = "properties.delete"
PERM_LEADS_VIEW = "leads.view"
PERM_LEADS_CREATE = "leads.create"
PERM_LEADS_EDIT_ALL = "leads.edit"
PERM_LEADS_EDIT_OWN = "leads.edit_own"
PERM_LEADS_DELETE = "leads.delete"
PERM_LEADS_ASSIGN = "leads.assign"
PERM_ASSISTANT = "assistant.use"
PERM_PLANNING_VIEW = "planning.view"
PERM_PLANNING_EDIT = "planning.edit"
PERM_USERS_MANAGE = "users.manage"
PERM_USERS_VIEW = "users.view"
PERM_AUDIT_VIEW = "audit.view"
PERM_FINANCE_VIEW = "finance.view"   # reserved: no finance module exists yet
PERM_HR_VIEW = "hr.view"             # reserved: salary/employee data is isolated

_ALL_PERMISSIONS = frozenset({
    PERM_DASHBOARD, PERM_PROPERTIES_VIEW, PERM_PROPERTIES_CREATE,
    PERM_PROPERTIES_EDIT, PERM_PROPERTIES_DELETE,
    PERM_LEADS_VIEW, PERM_LEADS_CREATE, PERM_LEADS_EDIT_ALL,
    PERM_LEADS_EDIT_OWN, PERM_LEADS_DELETE, PERM_LEADS_ASSIGN,
    PERM_ASSISTANT, PERM_PLANNING_VIEW, PERM_PLANNING_EDIT,
    PERM_USERS_MANAGE, PERM_USERS_VIEW, PERM_AUDIT_VIEW,
    PERM_FINANCE_VIEW, PERM_HR_VIEW,
})


def _staff(**kw):
    """Small builder so the matrix below reads clearly."""
    return kw


def _full(kw):
    kw.update({p: True for p in _ALL_PERMISSIONS})
    return kw


ROLE_PERMISSIONS = {
    ROLE_SUPER_ADMIN: _full({}),
    ROLE_COMPANY_ADMIN: _staff(
        dashboard_view=True, properties_view=True, properties_create=True,
        properties_edit=True, leads_view=True, leads_create=True,
        leads_edit=True, leads_assign=True, assistant_use=True,
        planning_view=True, planning_edit=True, users_view=True,
        audit_view=True, finance_view=True, hr_view=True,
    ),
    ROLE_SALES: _staff(
        dashboard_view=True, properties_view=True, leads_view=True,
        leads_create=True, leads_edit_own=True, leads_assign=True,
        assistant_use=True, planning_view=True,
    ),
    ROLE_MARKETING: _staff(
        dashboard_view=True, properties_view=True, leads_view=True,
        leads_create=True, assistant_use=True, planning_view=True,
    ),
    ROLE_FINANCE: _staff(
        dashboard_view=True, properties_view=True,
        assistant_use=True, planning_view=True, finance_view=True,
    ),
    ROLE_HR: _staff(
        dashboard_view=True, properties_view=True, assistant_use=True,
        planning_view=True, hr_view=True,
    ),
    ROLE_PROPERTY: _staff(
        dashboard_view=True, properties_view=True, properties_create=True,
        properties_edit=True, assistant_use=True, planning_view=True,
    ),
    ROLE_CLIENT: _staff(
        dashboard_view=True, properties_view=True, leads_view=True,
    ),
}

# Normalize the shorthand into plain permission-name sets at import time.
_PERMISSION_BY_ATTR = {
    "dashboard_view": PERM_DASHBOARD,
    "properties_view": PERM_PROPERTIES_VIEW,
    "properties_create": PERM_PROPERTIES_CREATE,
    "properties_edit": PERM_PROPERTIES_EDIT,
    "properties_delete": PERM_PROPERTIES_DELETE,
    "leads_view": PERM_LEADS_VIEW,
    "leads_create": PERM_LEADS_CREATE,
    "leads_edit": PERM_LEADS_EDIT_ALL,
    "leads_edit_own": PERM_LEADS_EDIT_OWN,
    "leads_delete": PERM_LEADS_DELETE,
    "leads_assign": PERM_LEADS_ASSIGN,
    "assistant_use": PERM_ASSISTANT,
    "planning_view": PERM_PLANNING_VIEW,
    "planning_edit": PERM_PLANNING_EDIT,
    "users_manage": PERM_USERS_MANAGE,
    "users_view": PERM_USERS_VIEW,
    "audit_view": PERM_AUDIT_VIEW,
    "finance_view": PERM_FINANCE_VIEW,
    "hr_view": PERM_HR_VIEW,
}

_ROLE_PERMISSION_SETS = {}
for _role, _flags in ROLE_PERMISSIONS.items():
    _set = set()
    for _attr, _perm in _PERMISSION_BY_ATTR.items():
        if _flags.get(_attr):
            _set.add(_perm)
    if _role == ROLE_SUPER_ADMIN:
        _set = set(_ALL_PERMISSIONS)
    _ROLE_PERMISSION_SETS[_role] = frozenset(_set)


def permissions_for_role(role_name):
    """Frozen set of permission names for a role (empty for unknown roles)."""
    return _ROLE_PERMISSION_SETS.get(role_name, frozenset())


def role_hierarchy():
    """Ordered role names, most privileged first (used by UIs/CLI)."""
    return list(ALL_ROLES)


# --------------------------------------------------------------------------- #
# User helpers
# --------------------------------------------------------------------------- #

def user_permissions(user):
    """Effective permission set for a user dict loaded from the DB."""
    if not user:
        return frozenset()
    perms = set()
    for role in get_user_roles(user["id"]):
        perms |= permissions_for_role(role)
    return frozenset(perms)


def can(user, permission):
    """True when the (possibly None) user holds the given permission."""
    if not user:
        return False
    return permission in user_permissions(user)


def user_roles(user):
    """Role names for the current user (cached on g)."""
    if not user:
        return ()
    cached = getattr(g, "_roles_cache", None)
    if cached is None:
        cached = tuple(get_user_roles(user["id"]))
        g._roles_cache = cached
    return cached


def is_client(user):
    return bool(user) and ROLE_CLIENT in user_roles(user)


# --------------------------------------------------------------------------- #
# Flask request helpers
# --------------------------------------------------------------------------- #

PUBLIC_ENDPOINTS = frozenset({"static", "auth.login"})


def load_user():
    """Populate g.user from the session (called in before_request)."""
    user_id = session.get("user_id")
    g.user = None
    g.client_only = False
    if user_id:
        user = get_user_by_id(user_id)
        if user:
            g.user = user
            g.client_only = is_client(user)
            if "roles" not in g:
                pass  # roles are resolved lazily in user_roles()


def logged_in():
    return getattr(g, "user", None) is not None


def login_required(view):
    """Route decorator: reject anonymous users (belt-and-braces on top of the
    global before_request guard, so routes work even if the guard changes)."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not logged_in():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthenticated"}), 401
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def permission_required(permission):
    """Route decorator: reject users who lack the permission."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not can(g.get("user"), permission):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Forbidden"}), 403
                return render_template(
                    "error.html",
                    code=403,
                    title="Access denied",
                    message="You do not have permission to access this page.",
                ), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


# --------------------------------------------------------------------------- #
# Session helpers
# --------------------------------------------------------------------------- #

def establish_session(user_id):
    """Fresh, protected session for a logged-in user.

    session.clear() removes any pre-login cookies (session fixation defence).
    The CSRF token is regenerated on the next request automatically.
    """
    session.clear()
    session["user_id"] = user_id
    session.permanent = True


def end_session():
    session.clear()


# --------------------------------------------------------------------------- #
# CSRF protection (manual, dependency-free)
# --------------------------------------------------------------------------- #

def _csrf_enabled():
    from config import CSRF_ENABLED
    return CSRF_ENABLED


def csrf_token():
    """Current session CSRF token, created on demand."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf():
    """Compare submitted token with the session token.

    The token is read from the form field 'csrf_token' or the
    'X-CSRFToken' header (used by the JS fetch to /api/assistant).
    Returns True when valid or when CSRF is disabled for the app.
    """
    if not _csrf_enabled():
        return True
    expected = session.get("csrf_token")
    if not expected:
        return False
    provided = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
    return secrets.compare_digest(str(provided), str(expected))


# --------------------------------------------------------------------------- #
# Audit helpers
# --------------------------------------------------------------------------- #

def audit(action, entity_type=None, entity_id=None, details=None):
    """Record an audit entry for the current user (if any). Never raises."""
    user = getattr(g, "user", None)
    return _write_audit(
        action=action,
        user_id=user["id"] if user else None,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=request.remote_addr if request else None,
        user_agent=request.user_agent.string[:255] if request else None,
    )


def audit_logs(limit=200):
    from database import get_audit_logs
    return get_audit_logs(limit=limit)


# --------------------------------------------------------------------------- #
# Rate limiting (single-process, in-memory — suitable for the dev stage)
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Sliding-window counter keyed by a string (client IP). Thread-safe."""

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            stamp = self._hits.get(key, [])
            stamp = [t for t in stamp if now - t < self.window]
            if len(stamp) >= self.limit:
                self._hits[key] = stamp
                return False
            stamp.append(now)
            self._hits[key] = stamp
            return True