"""
database.py
Handles all SQLite database operations for the Property CRM.
Beginner-friendly helper functions - no raw SQL needed in app.py.
"""

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
    "created_at": "TEXT DEFAULT (datetime('now'))",
}

# Same idea for the leads table (requirement columns used by matching/search).
LEAD_COLUMN_MIGRATION = {
    "needs_swimming_pool": "TEXT DEFAULT 'No'",
    "needs_nearby_metro": "TEXT DEFAULT 'No'",
    "preferred_location": "TEXT",
    "bedrooms_needed": "INTEGER",
    "notes": "TEXT",
}

VALID_STATUSES = ("Available", "Sold", "Rented")


def _ensure_columns(cur, table, expected):
    """Add any missing columns to an existing table (safe to run repeatedly)."""
    existing = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
    for column, declaration in expected.items():
        if column not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


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


def _valid_status(value):
    return value if value in VALID_STATUSES else "Available"


def get_connection():
    """Open a connection to SQLite with Row access (dict-like rows)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't already exist."""
    conn = get_connection()
    cur = conn.cursor()

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
            created_at TEXT DEFAULT (datetime('now'))
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
            created_at TEXT DEFAULT (datetime('now'))
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

    # --- automatic migration: upgrade older databases in place ---
    _ensure_columns(cur, "properties", PROPERTY_COLUMN_MIGRATION)
    _ensure_columns(cur, "leads", LEAD_COLUMN_MIGRATION)

    conn.commit()
    conn.close()


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
                 property_view, has_swimming_pool, nearby_metro, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_property(property_id, data):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE properties
            SET name=?, location=?, price=?, bedrooms=?, bathrooms=?, floor_number=?,
                property_view=?, has_swimming_pool=?, nearby_metro=?, status=?
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

def get_all_leads():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead(lead_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_lead(data):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO leads
                (client_name, phone, email, budget, preferred_location, bedrooms_needed,
                 needs_swimming_pool, needs_nearby_metro, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data.get("status", "New"),
                data.get("notes", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_lead(lead_id, data):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE leads
            SET client_name=?, phone=?, email=?, budget=?, preferred_location=?,
                bedrooms_needed=?, needs_swimming_pool=?, needs_nearby_metro=?,
                status=?, notes=?
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
                data.get("status", "New"),
                data.get("notes", ""),
                lead_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_lead(lead_id):
    conn = get_connection()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()


# ---------------------- DASHBOARD STATS ----------------------

def get_dashboard_stats():
    conn = get_connection()
    stats = {
        "total_properties": conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0],
        "available": conn.execute(
            "SELECT COUNT(*) FROM properties WHERE status = 'Available'"
        ).fetchone()[0],
        "sold": conn.execute(
            "SELECT COUNT(*) FROM properties WHERE status = 'Sold'"
        ).fetchone()[0],
        "rented": conn.execute(
            "SELECT COUNT(*) FROM properties WHERE status = 'Rented'"
        ).fetchone()[0],
        "total_leads": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
    }
    conn.close()
    return stats
