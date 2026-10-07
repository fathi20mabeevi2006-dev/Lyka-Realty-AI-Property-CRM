"""Phase 2 image upload tests. Run from project root."""
import base64
import io
import os
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
UPLOADS = app_module.UPLOAD_FOLDER

# Valid 1x1 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

BASE_FORM = {
    "name": "Image Upload Test Villa",
    "location": "Test City",
    "price": "7770000",
    "bedrooms": "3",
    "bathrooms": "2",
    "floor_number": "6",
    "property_view": "Sea View",
    "has_swimming_pool": "Yes",
    "nearby_metro": "No",
    "status": "Available",
}


def find_test_property():
    return [p for p in database.get_all_properties()
            if p["name"] == BASE_FORM["name"]]


# ------------------------------------------------ 1. FORM MARKUP
print("\n=== 1. Upload form markup ===")
resp = client.get("/properties/new")
html = resp.get_data(as_text=True)
check("add form -> 200", resp.status_code == 200)
check("add form is multipart", 'enctype="multipart/form-data"' in html)
check("add form has multi-file input", 'name="images"' in html and 'multiple' in html)


# ------------------------------------------------ 2. MULTI-UPLOAD
print("\n=== 2. Multi-image upload on add ===")
data = dict(BASE_FORM)
data["images"] = [
    (io.BytesIO(PNG), "photo_one.png"),
    (io.BytesIO(PNG), "photo_two.jpg"),
]
resp = client.post("/properties/new", data=data,
                   content_type="multipart/form-data", follow_redirects=True)
check("add with images -> 200", resp.status_code == 200)
added = find_test_property()
check("property created", len(added) == 1)
prop_id = added[0]["id"] if added else None

imgs = database.get_property_images(prop_id) if prop_id else []
check("2 image rows in DB", len(imgs) == 2, f"got {len(imgs)}")
files_exist = all(os.path.exists(os.path.join(UPLOADS, i["filename"])) for i in imgs)
check("2 image files on disk", files_exist and len(imgs) == 2)
check("stored filename is uuid-like (not client name)",
      all(i["filename"] != "photo_one.png" and len(i["filename"]) > 30 for i in imgs))

# ------------------------------------------------ 3. DISPLAY
print("\n=== 3. Gallery & thumbnail display ===")
resp = client.get(f"/properties/{prop_id}")
html = resp.get_data(as_text=True)
check("details page shows gallery-grid", "gallery-grid" in html)
check("details page embeds uploaded imgs",
      html.count("uploads/properties/") >= 2)

resp = client.get("/properties")
html = resp.get_data(as_text=True)
check("list page shows thumbnail", "row-thumb" in html and "uploads/properties/" in html)

# thumbnail subquery exposes filename in get_all_properties
row = [p for p in database.get_all_properties() if p["id"] == prop_id][0]
check("get_all_properties has thumbnail key",
      row.get("thumbnail") == imgs[0]["filename"], str(row.get("thumbnail")))


# ------------------------------------------------ 4. EDIT PAGE
print("\n=== 4. Edit page management ===")
resp = client.get(f"/properties/{prop_id}/edit")
html = resp.get_data(as_text=True)
check("edit page -> 200", resp.status_code == 200)
check("edit page shows Current Photos panel", "current-photos" in html)
check("edit page has per-image delete forms",
      html.count("/images/") >= 2 and "photo-remove" in html)
check("edit page file input present", 'name="images"' in html)

# add one more image via edit POST
data = {"name": BASE_FORM["name"], "location": BASE_FORM["location"],
        "price": BASE_FORM["price"], "bedrooms": "3", "bathrooms": "2",
        "floor_number": "6", "property_view": "Sea View",
        "has_swimming_pool": "Yes", "nearby_metro": "No", "status": "Available",
        "images": [(io.BytesIO(PNG), "third.png")]}
resp = client.post(f"/properties/{prop_id}/edit", data=data,
                   content_type="multipart/form-data", follow_redirects=True)
check("edit upload -> 200", resp.status_code == 200)
check("edit appended image (3 total)",
      len(database.get_property_images(prop_id)) == 3)


# ------------------------------------------------ 5. IMAGE DELETE
print("\n=== 5. Image deletion ===")
target = database.get_property_images(prop_id)[0]
target_path = os.path.join(UPLOADS, target["filename"])
resp = client.post(f"/properties/{prop_id}/images/{target['id']}/delete",
                   follow_redirects=True)
check("delete image -> 200", resp.status_code == 200)
check("image row deleted",
      database.get_property_image(target["id"]) is None)
check("image file removed from disk", not os.path.exists(target_path))
check("other images kept", len(database.get_property_images(prop_id)) == 2)

# cross-property delete is refused
other = database.get_all_properties()[-1]
resp = client.post(f"/properties/{other['id']}/images/{target['id']}/delete",
                   follow_redirects=True)
check("foreign image delete refused", resp.status_code == 200
      and database.get_property_images(prop_id).__len__() == 2)

# ------------------------------------------------ 6. VALIDATION
print("\n=== 6. Upload validation ===")
data = dict(BASE_FORM)
data["name"] = "Bad Extension Test"
data["images"] = [(io.BytesIO(b"not an image"), "evil.txt")]
resp = client.post("/properties/new", data=data,
                   content_type="multipart/form-data", follow_redirects=True)
bad = [p for p in database.get_all_properties() if p["name"] == "Bad Extension Test"]
check("bad extension: property still created", len(bad) == 1)
check("bad extension: no image rows", len(database.get_property_images(bad[0]["id"])) == 0)
stray = [f for f in os.listdir(UPLOADS) if f.startswith("evil")] if os.path.isdir(UPLOADS) else []
check("bad extension: no stray files", stray == [])
check("bad extension: flash message shown", "allowed types" in resp.get_data(as_text=True))
client.post(f"/properties/{bad[0]['id']}/delete", follow_redirects=True)

# oversized upload -> 413 handler redirects with flash
big = dict(BASE_FORM)
big["name"] = "Oversized Upload Test"
big["images"] = [(io.BytesIO(b"x" * (11 * 1024 * 1024)), "huge.png")]
resp = client.post("/properties/new", data=big,
                   content_type="multipart/form-data", follow_redirects=False)
check("oversized upload -> redirect (413 handler)",
      resp.status_code in (302, 303), f"got {resp.status_code}")
oversized = [p for p in database.get_all_properties()
             if p["name"] == "Oversized Upload Test"]
check("oversized: no property row created", len(oversized) == 0)


# ------------------------------------------------ 7. PROPERTY DELETE CLEANUP
print("\n=== 7. Property delete removes its files ===")
remaining = database.get_property_images(prop_id)
paths = [os.path.join(UPLOADS, i["filename"]) for i in remaining]
resp = client.post(f"/properties/{prop_id}/delete", follow_redirects=True)
check("property deleted", database.get_property(prop_id) is None)
check("its image rows deleted",
      len(database.get_property_images(prop_id)) == 0)
check("its files deleted from disk",
      not any(os.path.exists(p) for p in paths))


# ------------------------------------------------ 8. DATA INTEGRITY
print("\n=== 8. Existing data intact ===")
props = database.get_all_properties()
leads = database.get_all_leads()
check("20 properties intact", len(props) == 20, f"got {len(props)}")
check("8 leads intact", len(leads) == 8, f"got {len(leads)}")
check("user-added rows intact",
      any(p["name"].strip() == "Ahmed Khan" for p in props))


# ------------------------------------------------ 9. REGRESSION SUITES
print("\n=== 9. Regression suites ===")
for suite in ("_test_phase1.py", "_test_phase2.py"):
    result = subprocess.run([sys.executable, suite], cwd=ROOT,
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    last = (result.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
    check(f"{suite} passes", result.returncode == 0,
          f"rc={result.returncode}; {last}; stderr={(result.stderr or '')[:300]}")
    if result.returncode == 0:
        print(f"  ({last[0]})")

print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL IMAGE TESTS PASSED")
