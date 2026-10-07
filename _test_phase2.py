"""Phase 2 test suite — advanced property filters + instant search. Run from project root."""
import os
import re
import subprocess
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


import database
import app as app_module

app_module.app.config["TESTING"] = True
client = app_module.app.test_client()

ALL = database.get_all_properties()


def names(resp):
    """Property names visible in a filtered response body."""
    body = resp.get_data(as_text=True)
    return [p["name"] for p in ALL if f"data-name=\"{p['name']}\"" in body]


# ------------------------------------------------ 1. LEGACY BEHAVIOUR
print("\n=== 1. Existing filter behaviour preserved ===")
resp = client.get("/properties")
check("unfiltered page -> 200", resp.status_code == 200)
check("unfiltered shows all properties", len(names(resp)) == len(ALL),
      f"{len(names(resp))} vs {len(ALL)}")

resp = client.get("/properties?q=dubai")
body = resp.get_data(as_text=True)
check("legacy ?q=dubai works", resp.status_code == 200 and "Dubai" in body)
check("legacy ?q excludes non-matching", "Velachery" not in body)

sold_expected = [p["name"] for p in ALL if p["status"] == "Sold"]
resp = client.get("/properties?status=Sold")
got = names(resp)
check("legacy ?status=Sold exact set", sorted(got) == sorted(sold_expected),
      f"expected {len(sold_expected)}, got {len(got)}")

# ------------------------------------------------- 2. EACH NEW FILTER
print("\n=== 2. New server-side filters ===")

# Location
loc_expected = [p["name"] for p in ALL if "dubai" in (p["location"] or "").lower()]
resp = client.get("/properties?location=dubai")
check("?location=dubai exact set", sorted(names(resp)) == sorted(loc_expected))

# Price range
minp = 20000000
exp = [p["name"] for p in ALL if p["price"] >= minp]
resp = client.get(f"/properties?min_price={minp}")
check("?min_price filters correctly", sorted(names(resp)) == sorted(exp),
      f"expected {len(exp)}, got {len(names(resp))}")

maxp = 10000000
exp = [p["name"] for p in ALL if p["price"] <= maxp]
resp = client.get(f"/properties?max_price={maxp}")
check("?max_price filters correctly", sorted(names(resp)) == sorted(exp))

exp = [p["name"] for p in ALL if 5000000 <= p["price"] <= 15000000]
resp = client.get("/properties?min_price=5000000&max_price=15000000")
check("?min+max price range exact set", sorted(names(resp)) == sorted(exp))

# Bedrooms / bathrooms
exp = [p["name"] for p in ALL if p["bedrooms"] == 2]
resp = client.get("/properties?bedrooms=2")
check("?bedrooms=2 exact set", sorted(names(resp)) == sorted(exp))

exp = [p["name"] for p in ALL if p["bathrooms"] == 3]
resp = client.get("/properties?bathrooms=3")
check("?bathrooms=3 exact set", sorted(names(resp)) == sorted(exp))

# Pool / metro
exp = [p["name"] for p in ALL if p["has_swimming_pool"] == "Yes"]
resp = client.get("/properties?pool=Yes")
check("?pool=Yes exact set", sorted(names(resp)) == sorted(exp))

exp = [p["name"] for p in ALL if p["nearby_metro"] == "No"]
resp = client.get("/properties?metro=No")
check("?metro=No exact set", sorted(names(resp)) == sorted(exp))

# Property view
exp = [p["name"] for p in ALL if (p["property_view"] or "") == "Sea View"]
resp = client.get("/properties?view=Sea%20View")
check("?view=Sea View exact set", sorted(names(resp)) == sorted(exp))

resp = client.get("/properties?view=None")
check("?view=None shows server empty state",
      resp.status_code == 200 and "No properties found" in resp.get_data(as_text=True))

# Status (new value alongside legacy param — same param, unchanged)
exp = [p["name"] for p in ALL if p["status"] == "Available"]
resp = client.get("/properties?status=Available")
check("?status=Available exact set", sorted(names(resp)) == sorted(exp))

# --------------------------------------- 3. COMBINED + ROBUSTNESS
print("\n=== 3. Combined filters & robustness ===")
exp = [p["name"] for p in ALL
       if "dubai" in p["location"].lower() and p["bedrooms"] == 2
       and p["has_swimming_pool"] == "Yes"]
resp = client.get("/properties?location=Dubai&bedrooms=2&pool=Yes")
check("combined location+beds+pool", sorted(names(resp)) == sorted(exp),
      f"expected {exp}")

resp = client.get("/properties?min_price=abc&max_price=xyz")
check("invalid price inputs -> 200 (no crash)", resp.status_code == 200)
check("invalid price inputs ignored", len(names(resp)) == len(ALL))

resp = client.get("/properties?bedrooms=99&status=Bogus")
check("non-matching combo -> 200 empty state",
      resp.status_code == 200 and "No properties found" in resp.get_data(as_text=True))

# --------------------------------------- 4. MARKUP FOR INSTANT SEARCH
print("\n=== 4. Instant-search markup & assets ===")
resp = client.get("/properties")
body = resp.get_data(as_text=True)
check("filter form present", 'id="filterForm"' in body)
for field in ("q", "location", "price" , "bedrooms", "bathrooms", "pool", "metro", "view", "status"):
    check(f"filter control for {field.strip()}", f'name="{field}"' in body or f'name="min_{field}"' in body or f'name="max_{field}"' in body)
check("filters.js loaded", "js/filters.js" in body)
check("result counter present", "resultCount" in body)
check("client-side empty row present", "filterEmpty" in body)
check("rows carry data-price", 'data-price="' in body)
check("rows carry data-pool", 'data-pool="' in body)
check("rows carry data-view", 'data-view="' in body)
check("rows carry data-status", 'data-status="' in body)
check("rows carry data-bedrooms", 'data-bedrooms="' in body)

resp = client.get("/static/js/filters.js")
check("filters.js served -> 200", resp.status_code == 200)
js = resp.get_data(as_text=True)
check("filters.js implements debounce", "300" in js)
check("filters.js handles clear", "clearFilters" in js)

# dataset values match DB truth for a known row
sample = ALL[0]
check("row dataset matches DB",
      f'data-name="{sample["name"]}"' in body
      and f'data-price="{sample["price"]}"' in body
      and f'data-status="{sample["status"]}"' in body)

# ------------------------------------------ 5. DATA INTEGRITY
print("\n=== 5. Data integrity ===")
props = database.get_all_properties()
leads = database.get_all_leads()
check("20 properties intact", len(props) == 20, f"got {len(props)}")
check("8 leads intact", len(leads) == 8, f"got {len(leads)}")

# ------------------------------------------ 6. PHASE 1 REGRESSION
print("\n=== 6. Phase 1 regression suite ===")
result = subprocess.run([sys.executable, "_test_phase1.py"],
                        cwd=ROOT, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
tail = (result.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
check("phase1 suite passes", result.returncode == 0,
      f"rc={result.returncode}; {tail}; stderr={(result.stderr or '')[:300]}")
if result.returncode == 0:
    print(f"  ({tail[0]})")

print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL PHASE 2 TESTS PASSED")
