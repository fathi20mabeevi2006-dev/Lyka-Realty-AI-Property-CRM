"""
database.py
Handles all SQLite database operations for the Property CRM.
Beginner-friendly helper functions - no raw SQL needed in app.py.
"""

import json
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "crm.db")

# Columns that must exist on the properties table. If an older crm.db is
# missing any of them, init_db() adds them automatically with ALTER TABLE.
PROPERTY_COLUMN_MIGRATION = {
    "floor_number": "INTEGER",
    "property_view": "TEXT",
    "has_swimming_pool": "TEXT DEFAULT 'No'",
    "nearby_metro": "TEXT DEFAULT 'No'",
    "status": "TEXT DEFAULT 'Available'",
    "property_type": "TEXT",
    "property_size": "REAL",
    "created_at": "TEXT DEFAULT (datetime('now'))",
    "updated_at": "TEXT",
    # PRD §E — additive columns (existing rows keep their data; the defaults
    # below are applied to legacy rows by SQLite's ALTER TABLE semantics).
    "listing_purpose": "TEXT DEFAULT 'Sale'",
    "amenities": "TEXT",
    "currency": "TEXT",
    "area_sqft": "REAL",
    "description": "TEXT",
    "building_name": "TEXT",
    "agent_name": "TEXT",
    "is_demo": "INTEGER DEFAULT 0",
}

# Same idea for the leads table (requirement columns used by matching/search).
LEAD_COLUMN_MIGRATION = {
    "needs_swimming_pool": "TEXT DEFAULT 'No'",
    "needs_nearby_metro": "TEXT DEFAULT 'No'",
    "preferred_location": "TEXT",
    "bedrooms_needed": "INTEGER",
    "notes": "TEXT",
    "lead_source": "TEXT",
    "assigned_to": "TEXT",
    "next_follow_up": "TEXT",
    "last_contact": "TEXT",
    "lead_score": "INTEGER DEFAULT 0",
    "updated_at": "TEXT",
    "owner_user_id": "INTEGER",
    "client_user_id": "INTEGER",
    # PRD §B/C/D — extracted requirements, scoring breakdown and priority.
    "lead_type": "TEXT",
    "property_type": "TEXT",
    "bathrooms_needed": "INTEGER",
    "budget_min": "REAL",
    "budget_max": "REAL",
    "currency": "TEXT",
    "purpose": "TEXT",
    "amenities": "TEXT",
    "timeline_days": "INTEGER",
    "timeline_label": "TEXT",
    "missing_fields": "TEXT",
    "score_breakdown": "TEXT",
    "priority": "TEXT",
    "raw_enquiry": "TEXT",
    "analysis_provider": "TEXT",
    "analysed_at": "TEXT",
}


VALID_STATUSES = ("Available", "Sold", "Rented")

# --- business analysis workspace (Phase 3) ---
BUSINESS_CATEGORIES = (
    "Company Profile", "Business Model", "Objectives", "Target Customers",
    "Products & Services", "Customer Acquisition & Lead Sources",
    "Workflows & Communication Channels", "Software Platforms & Data Sources",
    "Challenges", "Risks & Contingency", "Improvement Opportunities", "Other",
)
SOURCE_TYPES = ("Fact", "Assumption", "Recommendation")
BUSINESS_STATUSES = ("Draft", "In Progress", "Reviewed", "Approved")

# --- requirements & gap analysis (Phase 3) ---
REQUIREMENT_TYPES = ("Functional", "Non-Functional")
PRIORITIES = ("High", "Medium", "Low")
REQUIREMENT_STATUSES = ("Draft", "Approved", "In Progress", "Done", "Deferred")
REQUIREMENT_CATEGORIES = (
    "Dashboard", "Property Management", "Leads & Clients", "AI & Automation",
    "Reporting", "Data Quality", "Security & Privacy", "Integration", "Other",
)


def _missing_columns(cur, table, expected):
    existing = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
    return [column for column in expected if column not in existing]


def _ensure_columns(cur, table, expected):
    """Add any missing columns to an existing table (safe to run repeatedly).

    Returns the columns that were actually added."""
    added = _missing_columns(cur, table, expected)
    for column in added:
        cur.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {expected[column]}"
        )
    return added


def _yn(value):
    """Normalize any Yes/No-ish input to exactly 'Yes' or 'No'."""
    return "Yes" if str(value or "").strip().lower() in ("yes", "y", "true", "1") else "No"


def _optional_int(value, field_label):
    """Empty → None, otherwise a non-negative int (raises ValueError if invalid)."""
    if value in (None, ""):
        return None
    number = int(value)
    if number < 0:
        raise ValueError(f"{field_label} cannot be negative")
    return number


def _optional_float(value, field_label):
    """Empty → None, otherwise a non-negative float (raises ValueError if invalid)."""
    if value in (None, ""):
        return None
    number = float(value)
    if number < 0:
        raise ValueError(f"{field_label} cannot be negative")
    return number


def _valid_status(value):
    return value if value in VALID_STATUSES else "Available"


# PRD §E — listing purpose is an explicit Sale/Rent choice. A blank value is
# allowed as an input meaning "not stated" (legacy/imported rows may have no
# recorded purpose); it is NEVER auto-guessed into Sale or Rent.
PROPERTY_PURPOSES = ("Sale", "Rent")


def _valid_purpose(value, default=None):
    """Canonicalise a listing purpose.

    - blank/None        -> `default` (caller decides: 'Sale' on create,
                           None on update so the stored value is preserved),
    - 'sale'/'Sale'/... -> 'Sale', 'rent'/'Rent'/... -> 'Rent',
    - anything else     -> ValueError (an invalid purpose is never persisted).
    """
    text = str(value or "").strip()
    if not text:
        return default
    for purpose in PROPERTY_PURPOSES:
        if text.lower() == purpose.lower():
            return purpose
    raise ValueError("Listing purpose must be Sale or Rent")


def _valid_choice(value, allowed, default):
    """Return value if it is in the allowed whitelist, else the default."""
    value = str(value or "").strip()
    return value if value in allowed else default


# PRD §G — the canonical lead pipeline. These are the values the UI offers
# and the API accepts for new writes.
LEAD_STATUSES = (
    "New", "Analysed", "Qualified", "Property Matched", "Follow-up",
    "Viewing Scheduled", "Converted", "Lost",
)

# Statuses that predate the PRD pipeline. Existing rows keep them (they are
# never rewritten) and they stay selectable so no historical record becomes
# invalid — new leads use LEAD_STATUSES.
LEGACY_LEAD_STATUSES = ("Contacted", "Closed")

ALL_LEAD_STATUSES = LEAD_STATUSES + LEGACY_LEAD_STATUSES


def _lead_score(data):
    """PRD §D — transparent 0-100 qualification score.

    Delegates to services.qualification so the weights live in exactly one
    place. Never raises: a scoring failure must not block a save.
    """
    try:
        from services.qualification import score_lead
        return score_lead(data)
    except Exception:  # noqa: BLE001 - fall back to "no score", never 500
        return {"score": 0, "priority": "Low", "breakdown": []}


def _optional_date(value):
    """Empty → None, otherwise a trimmed date string (browser sends YYYY-MM-DD)."""
    if value in (None, ""):
        return None
    return str(value).strip()


def get_connection():
    """Open a connection to SQLite with Row access (dict-like rows)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def backup_db():
    """Create a timestamped backup copy of the database (safe online backup).

    Uses SQLite's online backup API, so it is safe even if the app is running.
    The copy is stored under backups/ (git-ignored). Returns the backup path,
    or None when DB_PATH is not the real 'crm.db' (e.g. test copies) or the
    backup folder cannot be created.
    """
    if os.path.basename(DB_PATH) != "crm.db":
        return None
    backups_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(backups_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backups_dir, f"crm_backup_{stamp}.db")
    source = sqlite3.connect(DB_PATH)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return target


def init_db():
    """Create tables if they don't already exist."""
    conn = get_connection()
    cur = conn.cursor()

    existing_tables = {
        row[0] for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    # Phase 2 (authentication & access control) introduces four NEW tables.
    # Take a backup BEFORE adding them the first time so the migration is
    # fully reversible. Strictly additive — existing tables are untouched.
    if "users" not in existing_tables:
        backup_db()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            price REAL NOT NULL,
            bedrooms INTEGER NOT NULL,
            bathrooms INTEGER NOT NULL,
            floor_number INTEGER,
            property_view TEXT,
            has_swimming_pool TEXT DEFAULT 'No',
            nearby_metro TEXT DEFAULT 'No',
            status TEXT DEFAULT 'Available',
            property_type TEXT,
            property_size REAL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            budget REAL,
            preferred_location TEXT,
            bedrooms_needed INTEGER,
            needs_swimming_pool TEXT DEFAULT 'No',
            needs_nearby_metro TEXT DEFAULT 'No',
            status TEXT DEFAULT 'New',
            notes TEXT,
            lead_source TEXT,
            assigned_to TEXT,
            next_follow_up TEXT,
            last_contact TEXT,
            lead_score INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """
    )

    # New table for Phase 2 — existing tables are never altered.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS property_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    # New tables for Phase 3 — strictly additive, existing tables are untouched.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS business_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT DEFAULT 'Other',
            title TEXT NOT NULL,
            details TEXT,
            source_type TEXT DEFAULT 'Fact',
            status TEXT DEFAULT 'Draft',
            created_by TEXT DEFAULT 'local',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            problem TEXT,
            proposed_solution TEXT,
            req_type TEXT DEFAULT 'Functional',
            category TEXT DEFAULT 'Other',
            priority TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'Draft',
            owner TEXT,
            acceptance_criteria TEXT,
            dependencies TEXT,
            risks TEXT,
            current_state TEXT,
            desired_state TEXT,
            gap_notes TEXT,
            created_by TEXT DEFAULT 'local',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """
    )

    # --- automatic migration: upgrade older databases in place ---
    # Detect what is missing FIRST and back up before touching the schema,
    # so every additive migration stays reversible (never drops or rewrites).
    pending_migration = bool(
        _missing_columns(cur, "properties", PROPERTY_COLUMN_MIGRATION)
        or _missing_columns(cur, "leads", LEAD_COLUMN_MIGRATION)
        or "lead_notes" not in existing_tables
        or "lead_status_history" not in existing_tables
        or "recommendations" not in existing_tables
    )
    if pending_migration:
        backup_db()

    _ensure_columns(cur, "properties", PROPERTY_COLUMN_MIGRATION)
    _ensure_columns(cur, "leads", LEAD_COLUMN_MIGRATION)

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            author TEXT,
            body TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads (id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            changed_by TEXT,
            changed_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads (id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            property_id INTEGER,
            match_score INTEGER NOT NULL DEFAULT 0,
            reasons TEXT,
            mismatches TEXT,
            snapshot TEXT,
            engine_version TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads (id)
        )
        """
    )
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS idx_notes_lead ON lead_notes (lead_id)",
        "CREATE INDEX IF NOT EXISTS idx_status_history_lead "
        "ON lead_status_history (lead_id)",
        "CREATE INDEX IF NOT EXISTS idx_recommendations_lead "
        "ON recommendations (lead_id)",
    ):
        cur.execute(index_sql)

    # ---------------------- Phase 2: auth & access control ----------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT UNIQUE,
            full_name TEXT,
            department TEXT,
            password_hash TEXT NOT NULL,
            status TEXT DEFAULT 'Active',
            last_login_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
        """
    )

    # A user may hold several roles; permission = union of their roles.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, role_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (role_id) REFERENCES roles (id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_log_user
        ON audit_log (user_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_log_entity
        ON audit_log (entity_type, entity_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_leads_owner
        ON leads (owner_user_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_leads_client
        ON leads (client_user_id)
        """
    )

    # --- PRD §D: backfill the derived score/priority for lead rows created
    # --- before the PRD scoring rules existed. Derived columns only — the
    # --- source data of existing records is never modified.
    stale_leads = cur.execute(
        "SELECT * FROM leads WHERE priority IS NULL"
    ).fetchall()
    for row in stale_leads:
        result = _lead_score(dict(row))
        cur.execute(
            "UPDATE leads SET lead_score=?, priority=?, score_breakdown=? "
            "WHERE id=?",
            (result["score"], result["priority"],
             json.dumps(result["breakdown"]), row["id"]),
        )

    conn.commit()
    conn.close()


# ---------------------- USERS / ROLES / AUDIT (Phase 2) ----------------------

def create_user(username, password_hash, full_name=None, email=None,
                department=None, roles=None, status="Active"):
    """Create a user account with optional role names (validated). Returns id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users
                (username, password_hash, full_name, email, department, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (username or "").strip(),
                password_hash,
                (full_name or "").strip() or None,
                (email or "").strip() or None,
                (department or "").strip() or None,
                status if status in ("Active", "Suspended", "Disabled") else "Active",
            ),
        )
        user_id = cur.lastrowid
        if roles:
            _set_user_roles(cur, user_id, roles)
        conn.commit()
        return user_id
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
        ((username or "").strip(),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, username, email, full_name, department, status, "
        "last_login_at, created_at FROM users ORDER BY username ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user(user_id, full_name=None, email=None, department=None,
                status=None):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE users
            SET full_name=?, email=?, department=?, status=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                (full_name or "").strip() or None,
                (email or "").strip() or None,
                (department or "").strip() or None,
                status if status in ("Active", "Suspended", "Disabled") else "Active",
                user_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def set_user_password(user_id, password_hash):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=datetime('now') WHERE id=?",
            (password_hash, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_user_status(user_id, status):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET status=?, updated_at=datetime('now') WHERE id=?",
            (status if status in ("Active", "Suspended", "Disabled") else "Active",
             user_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_last_login(user_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET last_login_at=datetime('now') WHERE id=?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def role_names():
    """All role names currently stored, e.g. ('Super Admin', 'Sales/CRM', ...)."""
    conn = get_connection()
    names = [r["name"] for r in conn.execute(
        "SELECT name FROM roles ORDER BY id"
    ).fetchall()]
    conn.close()
    return tuple(names)


def bootstrap_roles():
    """Insert the eight agreed roles if missing. Idempotent."""
    conn = get_connection()
    try:
        existing = {r["name"] for r in conn.execute("SELECT name FROM roles")}
        for name, description in (
            ("Super Admin", "Full system access including user & audit management."),
            ("Company Admin", "Management visibility and operational control."),
            ("Sales/CRM", "Leads, pipeline, follow-ups and property viewing."),
            ("Marketing", "Campaigns and lead-generation source tracking."),
            ("Finance/Accounts", "Financial records: invoices, receipts, commissions."),
            ("HR/Employees", "Employee and internal workflows."),
            ("Property/Operations", "Property listings and maintenance operations."),
            ("Client", "External client portal; own records only."),
        ):
            if name not in existing:
                conn.execute(
                    "INSERT INTO roles (name, description) VALUES (?, ?)",
                    (name, description),
                )
        conn.commit()
    finally:
        conn.close()


def get_user_roles(user_id):
    """Role names for one user."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT r.name FROM roles r
        JOIN user_roles ur ON ur.role_id = r.id
        WHERE ur.user_id = ?
        ORDER BY r.id
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return [r["name"] for r in rows]


def set_user_roles(user_id, roles):
    """Replace the role set for a user with the given role names."""
    conn = get_connection()
    try:
        _set_user_roles(conn.cursor(), user_id, roles)
        conn.commit()
    finally:
        conn.close()


def _set_user_roles(cur, user_id, roles):
    """Shared helper: replace user_roles for a user with validated role names."""
    cur.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    known = {r["name"] for r in cur.execute("SELECT name FROM roles")}
    for name in roles or ():
        name = str(name).strip()
        if name in known:
            cur.execute(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT ?, id FROM roles WHERE name = ?",
                (user_id, name),
            )


def user_has_role(user_id, role_name):
    return role_name in get_user_roles(user_id)


def add_audit_log(action, user_id=None, entity_type=None, entity_id=None,
                  details=None, ip_address=None, user_agent=None):
    """Record one audit entry. Never raises — a logging failure must not break
    the main action. Returns the new id or None."""
    try:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_log
                    (user_id, action, entity_type, entity_id, details,
                     ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    action,
                    entity_type,
                    str(entity_id) if entity_id is not None else None,
                    details,
                    (ip_address or "")[:45] or None,
                    (user_agent or "")[:255] or None,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - audit must never break the app
        return None


def get_audit_logs(limit=200):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT a.*, u.username AS actor
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY a.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------- PROPERTIES ----------------------

def get_all_properties():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.*,
            (SELECT filename FROM property_images i
             WHERE i.property_id = p.id
             ORDER BY i.id LIMIT 1) AS thumbnail
        FROM properties p
        ORDER BY p.id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_property(property_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM properties WHERE id = ?", (property_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_property(data):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO properties
                (name, location, price, bedrooms, bathrooms, floor_number,
                 property_view, has_swimming_pool, nearby_metro, status,
                 property_type, property_size, listing_purpose)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"].strip(),
                data["location"].strip(),
                float(data["price"]),
                int(data["bedrooms"]),
                int(data["bathrooms"]),
                _optional_int(data.get("floor_number"), "Floor number"),
                data.get("property_view", ""),
                _yn(data.get("has_swimming_pool")),
                _yn(data.get("nearby_metro")),
                _valid_status(data.get("status")),
                (data.get("property_type") or "").strip() or None,
                _optional_float(data.get("property_size"), "Property size"),
                # Backward compatible: an omitted purpose keeps the historical
                # default ('Sale'); an explicit, validated choice otherwise.
                _valid_purpose(data.get("listing_purpose"), default="Sale"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_property(property_id, data):
    conn = get_connection()
    try:
        # Validate BEFORE touching the row. A blank/absent purpose maps to
        # None and COALESCE keeps the stored value, so a legacy row whose
        # purpose is unknown is never silently re-labelled on an unrelated edit.
        purpose = _valid_purpose(data.get("listing_purpose"), default=None)
        conn.execute(
            """
            UPDATE properties
            SET name=?, location=?, price=?, bedrooms=?, bathrooms=?, floor_number=?,
                property_view=?, has_swimming_pool=?, nearby_metro=?, status=?,
                property_type=?, property_size=?,
                listing_purpose=COALESCE(?, listing_purpose),
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                data["name"].strip(),
                data["location"].strip(),
                float(data["price"]),
                int(data["bedrooms"]),
                int(data["bathrooms"]),
                _optional_int(data.get("floor_number"), "Floor number"),
                data.get("property_view", ""),
                _yn(data.get("has_swimming_pool")),
                _yn(data.get("nearby_metro")),
                _valid_status(data.get("status")),
                (data.get("property_type") or "").strip() or None,
                _optional_float(data.get("property_size"), "Property size"),
                purpose,
                property_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_property(property_id):
    """Delete a property, its image rows; returns image filenames to remove from disk."""
    conn = get_connection()
    try:
        filenames = [
            r["filename"]
            for r in conn.execute(
                "SELECT filename FROM property_images WHERE property_id = ?",
                (property_id,),
            ).fetchall()
        ]
        conn.execute("DELETE FROM property_images WHERE property_id = ?", (property_id,))
        conn.execute("DELETE FROM properties WHERE id = ?", (property_id,))
        conn.commit()
        return filenames
    finally:
        conn.close()


# ---------------------- PROPERTY IMAGES ----------------------

def add_property_images(property_id, filenames):
    """Record saved image filenames for a property."""
    if not filenames:
        return
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO property_images (property_id, filename) VALUES (?, ?)",
            [(property_id, f) for f in filenames],
        )
        conn.commit()
    finally:
        conn.close()


def get_property_images(property_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM property_images WHERE property_id = ? ORDER BY id",
        (property_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_property_image(image_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM property_images WHERE id = ?", (image_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_property_image(image_id):
    """Delete one image row; returns its filename (caller removes the file)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM property_images WHERE id = ?", (image_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM property_images WHERE id = ?", (image_id,))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


# ---------------------- LEADS ----------------------

def _decode_lead(row):
    """Turn a raw lead row into a dict with JSON columns expanded to lists."""
    lead = dict(row)
    for column in ("amenities", "missing_fields", "score_breakdown"):
        if column in lead:
            lead[column] = _read_json_list(lead[column])
    return lead


def get_all_leads():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    conn.close()
    return [_decode_lead(r) for r in rows]


def get_lead(lead_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    return _decode_lead(row) if row else None


def _json_list(value):
    """Normalise a list-ish value to a JSON array string (or None)."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                value = [stripped]
        else:
            value = [part.strip() for part in stripped.split(",") if part.strip()]
    if not isinstance(value, (list, tuple)):
        value = [value]
    return json.dumps([str(v)[:200] for v in value][:50])


def _read_json_list(value):
    """Stored JSON array -> python list (never raises)."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def add_lead(data):
    conn = get_connection()
    try:
        cur = conn.cursor()
        scoring = _lead_score(data)
        status = _valid_choice(data.get("status"), ALL_LEAD_STATUSES, "New")
        cur.execute(
            """
            INSERT INTO leads
                (client_name, phone, email, budget, preferred_location,
                 bedrooms_needed, needs_swimming_pool, needs_nearby_metro,
                 status, notes, lead_source, assigned_to, next_follow_up,
                 last_contact, lead_score, owner_user_id, client_user_id,
                 lead_type, property_type, bathrooms_needed, budget_min,
                 budget_max, currency, purpose, amenities, timeline_days,
                 timeline_label, missing_fields, score_breakdown, priority,
                 raw_enquiry, analysis_provider, analysed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["client_name"],
                data.get("phone", ""),
                data.get("email", ""),
                float(data["budget"]) if data.get("budget") not in (None, "") else None,
                data.get("preferred_location", ""),
                int(data["bedrooms_needed"]) if data.get("bedrooms_needed") not in (None, "") else None,
                _yn(data.get("needs_swimming_pool")),
                _yn(data.get("needs_nearby_metro")),
                status,
                data.get("notes", ""),
                data.get("lead_source", "") or None,
                data.get("assigned_to", "") or None,
                _optional_date(data.get("next_follow_up")),
                _optional_date(data.get("last_contact")),
                scoring["score"],
                _optional_int(data.get("owner_user_id"), "Owner id") if data.get("owner_user_id") not in (None, "") else None,
                _optional_int(data.get("client_user_id"), "Client id") if data.get("client_user_id") not in (None, "") else None,
                (data.get("lead_type") or "").strip() or None,
                (data.get("property_type") or "").strip() or None,
                _optional_int(data.get("bathrooms_needed"), "Bathrooms"),
                _optional_float(data.get("budget_min"), "Minimum budget"),
                _optional_float(data.get("budget_max"), "Maximum budget"),
                (data.get("currency") or "").strip() or None,
                (data.get("purpose") or "").strip() or None,
                _json_list(data.get("amenities")),
                _optional_int(data.get("timeline_days"), "Timeline"),
                (data.get("timeline_label") or "").strip() or None,
                _json_list(data.get("missing_fields")),
                json.dumps(scoring["breakdown"]),
                scoring["priority"],
                (data.get("raw_enquiry") or "").strip() or None,
                (data.get("analysis_provider") or "").strip() or None,
                (data.get("analysed_at") or "").strip() or None,
            ),
        )
        lead_id = cur.lastrowid
        if status != "New":
            cur.execute(
                "INSERT INTO lead_status_history "
                "(lead_id, from_status, to_status, changed_by) "
                "VALUES (?, NULL, ?, ?)",
                (lead_id, status, (data.get("created_by") or "").strip() or None),
            )
        conn.commit()
        return lead_id
    finally:
        conn.close()


def update_lead(lead_id, data):
    conn = get_connection()
    try:
        # Ownership (owner_user_id / client_user_id) is row-level access
        # security. The edit form never renders these fields, so unless the
        # caller explicitly passes a value we PRESERVE the current owner —
        # otherwise a Sales user editing a lead would silently unassign it
        # and a linked Client would lose access to their own lead.
        existing = conn.execute(
            "SELECT owner_user_id, client_user_id, status FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
        if existing is None:
            raise ValueError("Lead not found")
        existing_owner = existing["owner_user_id"]
        existing_client = existing["client_user_id"]

        analysis_row = conn.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()

        def kept(column):
            """Value for an analysis column: submitted value, else stored one."""
            if column in data:
                return data[column]
            return analysis_row[column] if analysis_row else None

        owner_raw = data.get("owner_user_id", existing_owner)
        client_raw = data.get("client_user_id", existing_client)
        owner_value = (
            existing_owner
            if owner_raw in (None, "") else _optional_int(owner_raw, "Owner id")
        )
        client_value = (
            existing_client
            if client_raw in (None, "") else _optional_int(client_raw, "Client id")
        )

        # Re-score against the MERGED record, not just the submitted form.
        # The legacy edit form never renders the AI/analysis columns
        # (purpose, property_type, amenities, timeline, budget_min/max, ...),
        # so scoring only the submitted dict would silently drop the points a
        # lead already earned. Stored values are the base; anything the caller
        # actually submitted overrides them, so a real change still re-scores.
        scoring_input = dict(analysis_row) if analysis_row is not None else {}
        for json_column in ("amenities", "missing_fields"):
            if scoring_input.get(json_column) not in (None, ""):
                scoring_input[json_column] = _read_json_list(scoring_input[json_column])
        scoring_input.update(data)

        status = _valid_choice(data.get("status"), ALL_LEAD_STATUSES, "New")
        scoring = _lead_score(scoring_input)

        conn.execute(
            """
            UPDATE leads
            SET client_name=?, phone=?, email=?, budget=?, preferred_location=?,
                bedrooms_needed=?, needs_swimming_pool=?, needs_nearby_metro=?,
                status=?, notes=?, lead_source=?, assigned_to=?, next_follow_up=?,
                last_contact=?, lead_score=?, owner_user_id=?, client_user_id=?,
                lead_type=?, property_type=?, bathrooms_needed=?, budget_min=?,
                budget_max=?, currency=?, purpose=?, amenities=?,
                timeline_days=?, timeline_label=?, missing_fields=?,
                score_breakdown=?, priority=?, raw_enquiry=?,
                analysis_provider=?, analysed_at=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (
                data["client_name"],
                data.get("phone", ""),
                data.get("email", ""),
                float(data["budget"]) if data.get("budget") not in (None, "") else None,
                data.get("preferred_location", ""),
                int(data["bedrooms_needed"]) if data.get("bedrooms_needed") not in (None, "") else None,
                _yn(data.get("needs_swimming_pool")),
                _yn(data.get("needs_nearby_metro")),
                status,
                data.get("notes", ""),
                data.get("lead_source", "") or None,
                data.get("assigned_to", "") or None,
                _optional_date(data.get("next_follow_up")),
                _optional_date(data.get("last_contact")),
                scoring["score"],
                owner_value,
                client_value,
                (kept("lead_type") or "").strip() or None,
                (kept("property_type") or "").strip() or None,
                _optional_int(kept("bathrooms_needed"), "Bathrooms"),
                _optional_float(kept("budget_min"), "Minimum budget"),
                _optional_float(kept("budget_max"), "Maximum budget"),
                (kept("currency") or "").strip() or None,
                (kept("purpose") or "").strip() or None,
                _json_list(kept("amenities")),
                _optional_int(kept("timeline_days"), "Timeline"),
                (kept("timeline_label") or "").strip() or None,
                _json_list(kept("missing_fields")),
                json.dumps(scoring["breakdown"]),
                scoring["priority"],
                (kept("raw_enquiry") or "").strip() or None,
                (kept("analysis_provider") or "").strip() or None,
                (kept("analysed_at") or "").strip() or None,
                lead_id,
            ),
        )

        # PRD §G — record a timestamped history row when the status changed.
        if status != existing["status"]:
            conn.execute(
                "INSERT INTO lead_status_history "
                "(lead_id, from_status, to_status, changed_by) "
                "VALUES (?, ?, ?, ?)",
                (lead_id, existing["status"], status,
                 (data.get("changed_by") or "").strip() or None),
            )
        conn.commit()
    finally:
        conn.close()


def delete_lead(lead_id):
    conn = get_connection()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()


# ---------------------- LEAD NOTES / HISTORY / RECOMMENDATIONS ----------------------

def add_lead_note(lead_id, body, author=None):
    """PRD §G — append a timestamped follow-up note to a lead."""
    body = (body or "").strip()
    if not body:
        raise ValueError("Note text is required")
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO lead_notes (lead_id, author, body) VALUES (?, ?, ?)",
            (lead_id, (author or "").strip() or None, body[:4000]),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_lead_notes(lead_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lead_notes WHERE lead_id = ? ORDER BY id DESC",
        (lead_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead_status_history(lead_id):
    """PRD §G — timestamped history of status changes for a lead."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lead_status_history WHERE lead_id = ? "
        "ORDER BY id DESC",
        (lead_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _decode_recommendation(row):
    item = dict(row)
    for column, default in (("reasons", []), ("mismatches", []), ("snapshot", {})):
        raw = item.get(column)
        if raw in (None, ""):
            item[column] = default
            continue
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            decoded = default
        if isinstance(default, list) and not isinstance(decoded, list):
            decoded = default
        if isinstance(default, dict) and not isinstance(decoded, dict):
            decoded = default
        item[column] = decoded
    return item


def save_recommendations(lead_id, results, engine_version=None):
    """PRD §E/F — persist one recommendation run (all rows share `created_at`,
    which is what identifies the run). Previous runs are kept as history.
    Returns the run timestamp."""
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        for item in results:
            prop = item.get("property") or {}
            conn.execute(
                """
                INSERT INTO recommendations
                    (lead_id, property_id, match_score, reasons, mismatches,
                     snapshot, engine_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id,
                    item.get("property_id") or prop.get("id"),
                    int(item.get("match_score", item.get("score", 0)) or 0),
                    json.dumps(item.get("reasons") or []),
                    json.dumps(item.get("mismatches") or []),
                    json.dumps(prop),
                    engine_version,
                    run_at,
                ),
            )
        conn.commit()
        return run_at
    finally:
        conn.close()


def get_lead_recommendations(lead_id, limit=None):
    """Full recommendation history for a lead, newest run first."""
    conn = get_connection()
    query = (
        "SELECT * FROM recommendations WHERE lead_id = ? "
        "ORDER BY created_at DESC, match_score DESC, id DESC"
    )
    params = (lead_id,)
    if limit:
        query += " LIMIT ?"
        params = (lead_id, limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_decode_recommendation(r) for r in rows]


def get_latest_recommendations(lead_id):
    """The most recent recommendation run for a lead (empty list if none)."""
    conn = get_connection()
    latest = conn.execute(
        "SELECT MAX(created_at) FROM recommendations WHERE lead_id = ?",
        (lead_id,),
    ).fetchone()[0]
    if not latest:
        conn.close()
        return []
    rows = conn.execute(
        "SELECT * FROM recommendations WHERE lead_id = ? AND created_at = ? "
        "ORDER BY match_score DESC",
        (lead_id, latest),
    ).fetchall()
    conn.close()
    return [_decode_recommendation(r) for r in rows]


def get_recent_recommendations(limit=5):
    """Dashboard feed: newest recommendation rows joined to lead + property."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT r.*, l.client_name AS lead_name, l.priority AS lead_priority,
               p.name AS property_name, p.location AS property_location,
               p.price AS property_price, p.bedrooms AS property_bedrooms,
               p.property_type AS property_type,
               p.listing_purpose AS listing_purpose
        FROM recommendations r
        LEFT JOIN leads l ON l.id = r.lead_id
        LEFT JOIN properties p ON p.id = r.property_id
        ORDER BY r.created_at DESC, r.match_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [_decode_recommendation(r) for r in rows]


# ---------------------- DASHBOARD STATS ----------------------

def get_dashboard_stats():
    """Read-only headline counts plus safe price totals (never raises on empty DB)."""
    conn = get_connection()

    status_counts = {s: 0 for s in VALID_STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM properties GROUP BY status"):
        status_counts[row["status"]] = row["n"]

    price_row = conn.execute(
        """
        SELECT
            COUNT(price)             AS priced_count,
            COALESCE(SUM(price), 0)  AS portfolio_value,
            COALESCE(AVG(price), 0)  AS average_price
        FROM properties
        WHERE price IS NOT NULL
        """
    ).fetchone()

    total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    analysed_leads = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE analysed_at IS NOT NULL "
        "AND TRIM(analysed_at) <> ''"
    ).fetchone()[0]
    high_priority = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE priority = 'High'"
    ).fetchone()[0]
    matched_leads = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE status = 'Property Matched'"
    ).fetchone()[0]
    conn.close()

    return {
        "total_properties": sum(status_counts.values()),
        "available": status_counts.get("Available", 0),
        "sold": status_counts.get("Sold", 0),
        "rented": status_counts.get("Rented", 0),
        "total_leads": total_leads,
        "analysed_leads": analysed_leads,
        "high_priority_leads": high_priority,
        "matched_leads": matched_leads,
        "status_counts": status_counts,
        "priced_count": price_row["priced_count"] or 0,
        "portfolio_value": price_row["portfolio_value"] or 0,
        "average_price": price_row["average_price"] or 0,
    }


def get_location_distribution(limit=8):
    """Top locations by listing count. Extra locations are bundled into 'Other'."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT location, COUNT(*) AS n
        FROM properties
        WHERE location IS NOT NULL AND TRIM(location) <> ''
        GROUP BY location
        ORDER BY n DESC
        """
    ).fetchall()
    conn.close()

    items = [{"location": r["location"], "count": r["n"]} for r in rows]
    if len(items) > limit:
        top = items[:limit]
        other = sum(i["count"] for i in items[limit:])
        if other:
            top.append({"location": "Other", "count": other})
        items = top
    return items


def get_bedroom_distribution():
    """Listing count per bedroom number, in ascending bedroom order."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT bedrooms, COUNT(*) AS n
        FROM properties
        GROUP BY bedrooms
        ORDER BY bedrooms
        """
    ).fetchall()
    conn.close()
    return [{"bedrooms": r["bedrooms"], "count": r["n"]} for r in rows]


def get_lead_status_summary():
    """Lead counts per status plus safe budget totals (never raises on empty DB)."""
    conn = get_connection()

    # Every PRD status plus the legacy ones, so old rows still render.
    known = ALL_LEAD_STATUSES
    by_status = {s: 0 for s in known}
    by_priority = {"High": 0, "Medium": 0, "Low": 0}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status"):
        if row["status"] not in by_status:
            by_status[row["status"]] = 0
        by_status[row["status"]] = row["n"]
    for row in conn.execute(
        "SELECT priority, COUNT(*) AS n FROM leads GROUP BY priority"
    ):
        if row["priority"] in by_priority:
            by_priority[row["priority"]] = row["n"]

    budget_row = conn.execute(
        """
        SELECT
            COUNT(budget)             AS budgeted_count,
            COALESCE(SUM(budget), 0)  AS total_budget,
            COALESCE(AVG(budget), 0)  AS average_budget
        FROM leads
        WHERE budget IS NOT NULL
        """
    ).fetchone()
    conn.close()

    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_priority": by_priority,
        "max_status": max(by_status.values()) if by_status else 0,
        "budgeted_count": budget_row["budgeted_count"] or 0,
        "total_budget": budget_row["total_budget"] or 0,
        "average_budget": budget_row["average_budget"] or 0,
    }


def get_recent_properties(limit=6):
    """Newest listings (with first image thumbnail) using a real LIMIT query."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.*,
            (SELECT filename FROM property_images i
             WHERE i.property_id = p.id
             ORDER BY i.id LIMIT 1) AS thumbnail
        FROM properties p
        ORDER BY p.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_leads(limit=5):
    """Newest leads using a real LIMIT query."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_follow_ups(limit=6):
    """Leads with a scheduled follow-up that is today or already past (overdue).

    Comparison uses date('now') so only the date part matters; the stored
    format is YYYY-MM-DD. Oldest follow-ups are shown first.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM leads
        WHERE next_follow_up IS NOT NULL
          AND TRIM(next_follow_up) <> ''
          AND next_follow_up <= date('now')
        ORDER BY next_follow_up ASC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------- BUSINESS ANALYSIS (Phase 3) ----------------------

def get_all_business_entries(category="", source_type="", status="", q=""):
    """All business analysis records, newest edit first, with optional filters."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM business_analysis
        ORDER BY updated_at DESC, id DESC
        """
    ).fetchall()
    conn.close()
    items = [dict(r) for r in rows]

    if category:
        items = [i for i in items if i["category"] == category]
    if source_type:
        items = [i for i in items if i["source_type"] == source_type]
    if status:
        items = [i for i in items if i["status"] == status]
    if q:
        ql = q.lower()
        items = [
            i for i in items
            if ql in (i["title"] or "").lower() or ql in (i["details"] or "").lower()
        ]
    return items


def get_business_entry(entry_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM business_analysis WHERE id = ?", (entry_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_business_entry(data):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required")
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO business_analysis
                (category, title, details, source_type, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _valid_choice(data.get("category"), BUSINESS_CATEGORIES, "Other"),
                title,
                (data.get("details") or "").strip(),
                _valid_choice(data.get("source_type"), SOURCE_TYPES, "Fact"),
                _valid_choice(data.get("status"), BUSINESS_STATUSES, "Draft"),
                (data.get("created_by") or "").strip() or "local",
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_business_entry(entry_id, data):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required")
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE business_analysis
            SET category=?, title=?, details=?, source_type=?, status=?,
                created_by=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (
                _valid_choice(data.get("category"), BUSINESS_CATEGORIES, "Other"),
                title,
                (data.get("details") or "").strip(),
                _valid_choice(data.get("source_type"), SOURCE_TYPES, "Fact"),
                _valid_choice(data.get("status"), BUSINESS_STATUSES, "Draft"),
                (data.get("created_by") or "").strip() or "local",
                entry_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_business_entry(entry_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM business_analysis WHERE id = ?", (entry_id,))
        conn.commit()
    finally:
        conn.close()


def get_business_summary():
    """Counts of business analysis records by category, source type and status."""
    conn = get_connection()
    by_category = dict(conn.execute(
        "SELECT category, COUNT(*) FROM business_analysis GROUP BY category"
    ).fetchall())
    by_source = dict(conn.execute(
        "SELECT source_type, COUNT(*) FROM business_analysis GROUP BY source_type"
    ).fetchall())
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM business_analysis GROUP BY status"
    ).fetchall())
    total = conn.execute("SELECT COUNT(*) FROM business_analysis").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "by_category": by_category,
        "by_source": by_source,
        "by_status": by_status,
    }


# ---------------------- REQUIREMENTS & GAP ANALYSIS (Phase 3) ----------------------

def get_all_requirements(req_type="", priority="", status="", category="", q=""):
    """All requirements, newest edit first, with optional filters."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM requirements
        ORDER BY updated_at DESC, id DESC
        """
    ).fetchall()
    conn.close()
    items = [dict(r) for r in rows]

    if req_type:
        items = [i for i in items if i["req_type"] == req_type]
    if priority:
        items = [i for i in items if i["priority"] == priority]
    if status:
        items = [i for i in items if i["status"] == status]
    if category:
        items = [i for i in items if i["category"] == category]
    if q:
        ql = q.lower()
        items = [
            i for i in items
            if ql in (i["title"] or "").lower()
            or ql in (i["description"] or "").lower()
            or ql in (i["problem"] or "").lower()
            or ql in (i["owner"] or "").lower()
        ]
    return items


def get_requirement(req_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM requirements WHERE id = ?", (req_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_requirement(data):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required")
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO requirements
                (title, description, problem, proposed_solution, req_type,
                 category, priority, status, owner, acceptance_criteria,
                 dependencies, risks, current_state, desired_state, gap_notes,
                 created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                (data.get("description") or "").strip(),
                (data.get("problem") or "").strip(),
                (data.get("proposed_solution") or "").strip(),
                _valid_choice(data.get("req_type"), REQUIREMENT_TYPES, "Functional"),
                _valid_choice(data.get("category"), REQUIREMENT_CATEGORIES, "Other"),
                _valid_choice(data.get("priority"), PRIORITIES, "Medium"),
                _valid_choice(data.get("status"), REQUIREMENT_STATUSES, "Draft"),
                (data.get("owner") or "").strip(),
                (data.get("acceptance_criteria") or "").strip(),
                (data.get("dependencies") or "").strip(),
                (data.get("risks") or "").strip(),
                (data.get("current_state") or "").strip(),
                (data.get("desired_state") or "").strip(),
                (data.get("gap_notes") or "").strip(),
                (data.get("created_by") or "").strip() or "local",
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_requirement(req_id, data):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required")
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE requirements
            SET title=?, description=?, problem=?, proposed_solution=?, req_type=?,
                category=?, priority=?, status=?, owner=?, acceptance_criteria=?,
                dependencies=?, risks=?, current_state=?, desired_state=?,
                gap_notes=?, created_by=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (
                title,
                (data.get("description") or "").strip(),
                (data.get("problem") or "").strip(),
                (data.get("proposed_solution") or "").strip(),
                _valid_choice(data.get("req_type"), REQUIREMENT_TYPES, "Functional"),
                _valid_choice(data.get("category"), REQUIREMENT_CATEGORIES, "Other"),
                _valid_choice(data.get("priority"), PRIORITIES, "Medium"),
                _valid_choice(data.get("status"), REQUIREMENT_STATUSES, "Draft"),
                (data.get("owner") or "").strip(),
                (data.get("acceptance_criteria") or "").strip(),
                (data.get("dependencies") or "").strip(),
                (data.get("risks") or "").strip(),
                (data.get("current_state") or "").strip(),
                (data.get("desired_state") or "").strip(),
                (data.get("gap_notes") or "").strip(),
                (data.get("created_by") or "").strip() or "local",
                req_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_requirement(req_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM requirements WHERE id = ?", (req_id,))
        conn.commit()
    finally:
        conn.close()


def get_requirement_summary():
    """Counts of requirements by type, priority and status."""
    conn = get_connection()
    by_type = dict(conn.execute(
        "SELECT req_type, COUNT(*) FROM requirements GROUP BY req_type"
    ).fetchall())
    by_priority = dict(conn.execute(
        "SELECT priority, COUNT(*) FROM requirements GROUP BY priority"
    ).fetchall())
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM requirements GROUP BY status"
    ).fetchall())
    total = conn.execute("SELECT COUNT(*) FROM requirements").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "by_type": by_type,
        "by_priority": by_priority,
        "by_status": by_status,
    }


PRIORITY_RANK = {"High": 3, "Medium": 2, "Low": 1}


def get_gap_analysis():
    """Derived gap view: a requirement is a gap when current_state and
    desired_state are both filled in but differ, or gap_notes are present.

    Returns items sorted by descending priority, each flagged with has_gap.
    """
    conn = get_connection()
    rows = conn.execute("SELECT * FROM requirements").fetchall()
    conn.close()
    items = []
    gap_count = 0
    for r in rows:
        rec = dict(r)
        current = (rec.get("current_state") or "").strip()
        desired = (rec.get("desired_state") or "").strip()
        has_gap = (bool(current and desired) and current != desired) or bool(
            (rec.get("gap_notes") or "").strip()
        )
        rec["has_gap"] = has_gap
        items.append(rec)
        if has_gap:
            gap_count += 1
    items.sort(
        key=lambda x: (PRIORITY_RANK.get(x.get("priority"), 0), x.get("id", 0)),
        reverse=True,
    )
    return {
        "items": items,
        "total": len(items),
        "gap_count": gap_count,
    }
