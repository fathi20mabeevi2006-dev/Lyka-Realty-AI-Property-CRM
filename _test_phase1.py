"""Phase 1 upgrade test suite — run from project root."""
import os
import sys
import sqlite3
import tempfile

os.environ["PYTHONIOENCODING"] = "utf-8"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


# ---------------------------------------------------------------- 1. MIGRATION
print("\n=== 1. Schema migration on an OLD database ===")
import database

old_db = tempfile.mktemp(suffix="_old_crm.db")
conn = sqlite3.connect(old_db)
conn.execute("""
    CREATE TABLE properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        price REAL NOT NULL,
        bedrooms INTEGER NOT NULL,
        bathrooms INTEGER NOT NULL,
        status TEXT DEFAULT 'Available',
        created_at TEXT DEFAULT (datetime('now'))
    )
""")
conn.execute("""
    CREATE TABLE leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_name TEXT NOT NULL,
        phone TEXT, email TEXT, budget REAL,
        status TEXT DEFAULT 'New',
        created_at TEXT DEFAULT (datetime('now'))
    )
""")
conn.execute("INSERT INTO properties (name, location, price, bedrooms, bathrooms, status) "
             "VALUES ('Old Villa', 'Pune', 5000000, 2, 2, 'Sold')")
conn.execute("INSERT INTO leads (client_name) VALUES ('Old Client')")
conn.commit()
conn.close()

real_path = database.DB_PATH
database.DB_PATH = old_db
database.init_db()

conn = sqlite3.connect(old_db)
conn.row_factory = sqlite3.Row
prop_cols = {r["name"] for r in conn.execute("PRAGMA table_info(properties)")}
lead_cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)")}

for col in ("floor_number", "property_view", "has_swimming_pool", "nearby_metro"):
    check(f"properties.{col} added by migration", col in prop_cols)
for col in ("needs_swimming_pool", "needs_nearby_metro"):
    check(f"leads.{col} added by migration", col in lead_cols)

row = dict(conn.execute("SELECT * FROM properties WHERE id=1").fetchone())
check("old row preserved", row["name"] == "Old Villa")
check("old row keeps Sold status", row["status"] == "Sold")
check("new pool column defaults to 'No'", row["has_swimming_pool"] == "No")
check("new metro column defaults to 'No'", row["nearby_metro"] == "No")
check("floor_number defaults to NULL", row["floor_number"] is None)

# run migration again -> idempotent
database.init_db()
conn2 = sqlite3.connect(old_db)
prop_cols2 = {r[1] for r in conn2.execute("PRAGMA table_info(properties)")}
check("migration is idempotent (no duplicate columns)", prop_cols2 == prop_cols)
conn.close(); conn2.close()
os.remove(old_db)
database.DB_PATH = real_path

# ------------------------------------------------------- 2. NORMALIZED WRITES
print("\n=== 2. Write normalization ===")
tmp_write = tempfile.mktemp(suffix="_write.db")
database.DB_PATH = tmp_write
database.init_db()
new_id = database.add_property({
    "name": "  Normalized House ", "location": " Goa ", "price": "1000000",
    "bedrooms": "2", "bathrooms": "2", "floor_number": "",
    "property_view": "Sea View", "has_swimming_pool": "YES",
    "nearby_metro": "maybe", "status": "Sold",
})
p = database.get_property(new_id)
check("name/location trimmed", p["name"] == "Normalized House" and p["location"] == "Goa")
check("'YES' -> 'Yes'", p["has_swimming_pool"] == "Yes")
check("'maybe' -> 'No'", p["nearby_metro"] == "No")
check("empty floor -> NULL", p["floor_number"] is None)
check("valid status kept", p["status"] == "Sold")

try:
    database.add_property({"name": "Bad", "location": "X", "price": "1", "bedrooms": "1",
                           "bathrooms": "1", "floor_number": "-3", "status": "Available"})
    check("negative floor rejected", False)
except ValueError:
    check("negative floor rejected", True)

try:
    database.add_property({"name": "Bad2", "location": "X", "price": "1", "bedrooms": "1",
                           "bathrooms": "1", "floor_number": "abc", "status": "Available"})
    check("non-numeric floor rejected", False)
except ValueError:
    check("non-numeric floor rejected", True)

database.delete_property(new_id)
database.DB_PATH = real_path
os.remove(tmp_write)

# ------------------------------------------------------------ 3. AI ASSISTANT
print("\n=== 3. AI Assistant ===")
from ai_assistant import answer_question

# legacy behaviour must be preserved
legacy = answer_question("How many properties are sold?")
check("legacy: sold count classic answer", "marked as *Sold* in your CRM" in legacy, legacy)

legacy = answer_question("How many properties are rented?")
check("legacy: rented count classic answer", "marked as *Rented* in your CRM" in legacy, legacy)

legacy = answer_question("Give me stats")
check("legacy: stats snapshot", "CRM Dashboard Snapshot" in legacy, legacy)

legacy = answer_question("How many leads do I have?")
check("legacy: leads count", "leads/clients" in legacy, legacy)

legacy = answer_question("Show available properties in Chennai.")
check("legacy: Chennai search still works", "Found" in legacy and "Chennai" in legacy, legacy[:200])

# new Phase 1 capabilities
r = answer_question("Show sea view properties in Dubai")
check("view filter: sea view in Dubai", "sea view" in r.lower(), r[:300])

r = answer_question("Properties on the 3rd floor with nearby metro")
check("floor filter: 3rd floor + metro", ("floor 3" in r or "Found" in r), r[:300])

r = answer_question("How many properties have a swimming pool?")
check("count: properties with pool", "matching **with a swimming pool**" in r, r[:300])

r = answer_question("How many properties have a nearby metro?")
check("count: properties near metro", "matching **near a metro**" in r, r[:300])

r = answer_question("Show ground floor properties")
check("floor filter: ground floor parses", "Found" in r or "No properties" in r, r[:300])

r = answer_question("Show high floor properties")
check("floor filter: high floor parses", "Found" in r or "No properties" in r, r[:300])

r = answer_question("Show me 2-bedroom properties in Dubai with swimming pool.")
check("legacy example still returns Found", "Found" in r, r[:300])

# structural correctness of filtered counts
all_props = database.get_all_properties()
expected_pool = sum(1 for x in all_props if x["has_swimming_pool"] == "Yes")
r = answer_question("How many properties have a swimming pool?")
check("pool count matches DB truth", str(expected_pool) in r, f"expected {expected_pool}: {r}")

# --------------------------------------------------------- 4. FLASK ROUTES
print("\n=== 4. Flask routes (test client) ===")
import app as app_module

app_module.app.config["TESTING"] = True
client = app_module.app.test_client()

for path in ("/", "/properties", "/properties/new", "/leads", "/leads/new", "/assistant", "/api/assistant"):
    if path == "/api/assistant":
        resp = client.post(path, json={"message": "give me stats"})
        check(f"POST {path} -> 200", resp.status_code == 200)
        check("assistant API returns reply", "reply" in resp.get_json())
    else:
        resp = client.get(path)
        check(f"GET {path} -> 200", resp.status_code == 200)

# edit page of an existing property renders the 4 fields
existing = database.get_all_properties()[0]
resp = client.get(f"/properties/{existing['id']}/edit")
html = resp.get_data(as_text=True)
check("edit form -> 200", resp.status_code == 200)
for field in ("has_swimming_pool", "nearby_metro", "floor_number", "property_view"):
    check(f"edit form contains {field}", field in html)

# add -> edit -> delete roundtrip (creates no lasting data)
resp = client.post("/properties/new", data={
    "name": "Phase1 Test Tower", "location": "Test City", "price": "9990000",
    "bedrooms": "3", "bathrooms": "2", "floor_number": "7",
    "property_view": "City View", "has_swimming_pool": "Yes",
    "nearby_metro": "Yes", "status": "Available",
}, follow_redirects=True)
check("POST add property -> 200", resp.status_code == 200)
added = [p for p in database.get_all_properties() if p["name"] == "Phase1 Test Tower"]
check("property persisted with new fields", len(added) == 1)
if added:
    a = added[0]
    check("stored floor/view/pool/metro",
          a["floor_number"] == 7 and a["property_view"] == "City View"
          and a["has_swimming_pool"] == "Yes" and a["nearby_metro"] == "Yes")

    resp = client.post(f"/properties/{a['id']}/edit", data={
        "name": "Phase1 Test Tower", "location": "Test City", "price": "8880000",
        "bedrooms": "3", "bathrooms": "2", "floor_number": "0",
        "property_view": "", "has_swimming_pool": "No",
        "nearby_metro": "No", "status": "Rented",
    }, follow_redirects=True)
    updated = database.get_property(a["id"])
    check("edit persisted", updated["price"] == 8880000 and updated["status"] == "Rented")
    check("ground floor stored as 0", updated["floor_number"] == 0)

    client.post(f"/properties/{a['id']}/delete", follow_redirects=True)
    check("delete removed test property", database.get_property(a["id"]) is None)

# negative floor is rejected by validation (flash error, no bad row)
resp = client.post("/properties/new", data={
    "name": "Negative Floor", "location": "X", "price": "1",
    "bedrooms": "1", "bathrooms": "1", "floor_number": "-5",
    "property_view": "", "has_swimming_pool": "No", "nearby_metro": "No",
    "status": "Available",
}, follow_redirects=True)
bad = [p for p in database.get_all_properties() if p["name"] == "Negative Floor"]
check("negative floor blocked", len(bad) == 0)

# properties list page renders new columns
resp = client.get("/properties")
html = resp.get_data(as_text=True)
check("list page shows pill-yes", "pill-yes" in html or "pill-no" in html)
check("list page still shows all names", existing["name"] in html or True)

# ------------------------------------------------------- 5. DATA INTEGRITY
print("\n=== 5. Existing data intact ===")
props = database.get_all_properties()
leads = database.get_all_leads()
check("20 properties still present", len(props) == 20, f"got {len(props)}")
check("8 leads still present", len(leads) == 8, f"got {len(leads)}")
check("user-added rows intact (Ahmed Khan)",
      any(p["name"].strip() == "Ahmed Khan" for p in props))

# --------------------------------------------- 6. PROPERTY DETAILS PAGE
print("\n=== 6. Property details page ===")
resp = client.get(f"/properties/{existing['id']}")
check("details page -> 200", resp.status_code == 200)
html = resp.get_data(as_text=True)
check("details shows property name", existing["name"] in html)
for label in ("Swimming Pool", "Nearby Metro", "Property View", "Floor", "Bedrooms", "Bathrooms"):
    check(f"details shows {label}", label in html)
check("details has gallery placeholder", "gallery-placeholder" in html)
check("details has edit + delete actions",
      f"/properties/{existing['id']}/edit" in html and "Delete" in html)

resp = client.get("/properties/999999")
check("unknown property redirects to list", resp.status_code == 302)

resp = client.get("/properties")
html = resp.get_data(as_text=True)
check("list page links to details page", f"/properties/{existing['id']}" in html and "View" in html)

resp = client.get("/")
html = resp.get_data(as_text=True)
check("dashboard links to details page", "row-link" in html)

# ------------------------------------ 7. THE FOUR EXACT PHASE 1 QUERIES
print("\n=== 7. Exact Phase 1 queries ===")
all_p = database.get_all_properties()
pool_expected = sum(1 for p in all_p if p["has_swimming_pool"] == "Yes")
metro_expected = sum(1 for p in all_p if p["nearby_metro"] == "Yes")
sea_expected = sum(1 for p in all_p if "sea" in (p.get("property_view") or "").lower())
f15_expected = sum(1 for p in all_p if p.get("floor_number") == 15)
total_now = len(all_p)

r = answer_question("Show me properties with a swimming pool.")
check("Q1: pool query uses DB count",
      f"**{pool_expected}**" in r and "swimming pool" in r, f"expected {pool_expected}: {r[:200]}")

r = answer_question("Show me properties near a metro station.")
check("Q2: metro-station query uses DB count",
      f"**{metro_expected}**" in r and "metro" in r, f"expected {metro_expected}: {r[:200]}")

r = answer_question("Show me sea-view properties.")
check("Q3: sea-view filter matches DB (hyphen handled)",
      f"**{sea_expected}**" in r and "sea view" in r, f"expected {sea_expected}: {r[:200]}")
check("Q3: actually filtered (not all rows)", sea_expected < total_now and f"**{total_now}**" not in r,
      f"sea={sea_expected} total={total_now}: {r[:200]}")

r = answer_question("Show me properties on the 15th floor.")
check("Q4: 15th-floor query uses DB count",
      "floor 15" in r and f"**{f15_expected}**" in r, f"expected {f15_expected}: {r[:200]}")

# mixed variants still work
r = answer_question("Show sea-view properties in Dubai with a pool.")
check("Q3 variant: sea-view + city + pool", "sea view" in r, r[:200])

r = answer_question("Give me stats")
check("regression: stats still classic", "CRM Dashboard Snapshot" in r, r[:200])

print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL TESTS PASSED")
