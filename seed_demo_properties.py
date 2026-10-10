"""
seed_demo_properties.py
Add demo listings used by the property-matching / recommendation engine.

These rows are ADDITIVE and clearly marked `is_demo = 1`, so they can be
told apart from the imported production data and removed at any time
(`DELETE FROM properties WHERE is_demo = 1`). The script is idempotent:
running it twice does not create duplicates.

Every listing carries a real `property_type`, a `listing_purpose`
('Sale' or 'Rent') and a JSON `amenities` list, which the matcher uses.
Run:
    python seed_demo_properties.py
"""

import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from database import init_db, get_connection

# (name, location, price, bedrooms, bathrooms, property_type, listing_purpose,
#  area_sqft, amenities, has_swimming_pool, nearby_metro, description)
DEMO_PROPERTIES = [
    # --- Dubai Marina (Sale) ---
    ("Marina Gate 2-Bed Apartment", "Dubai Marina", 1800000, 2, 2, "Apartment",
     "Sale", 1180, ["Swimming pool", "Gym", "Covered parking", "Balcony"],
     "Yes", "Yes", "Bright 2-bedroom in Marina Gate with full marina views."),
    ("Emaar 52|42 Marina Apartment", "Dubai Marina", 2350000, 3, 3, "Apartment",
     "Sale", 1580, ["Swimming pool", "Gym", "Nearby metro", "Security"],
     "Yes", "Yes", "Three-bedroom with panoramic views of Dubai Marina."),
    # --- Downtown Dubai (Sale) ---
    ("Burj Vista 2-Bed", "Downtown Dubai", 3100000, 2, 3, "Apartment",
     "Sale", 1240, ["Swimming pool", "Gym", "Nearby metro", "Balcony"],
     "Yes", "Yes", "Direct Burj Khalifa views, steps from Dubai Mall."),
    # --- Jumeirah Village Circle (Sale) ---
    ("Bloom Towers Studio", "Jumeirah Village Circle", 620000, 0, 1, "Studio",
     "Sale", 460, ["Gym", "Covered parking"], "Yes", "No",
     "Affordable studio ideal for first-time buyers."),
    ("Vincitore Boulevard 2-Bed", "Jumeirah Village Circle", 1150000, 2, 2, "Apartment",
     "Sale", 1050, ["Swimming pool", "Gym", "Covered parking", "Balcony"],
     "Yes", "No", "Family-friendly 2-bedroom with community pool."),
    # --- Townhouse / Villa (Sale) ---
    ("Damac Hills 3-Bed Townhouse", "Damac Hills", 2400000, 3, 4, "Townhouse",
     "Sale", 2100, ["Private pool", "Garden", "Covered parking", "Security"],
     "Yes", "No", "Spacious townhouse overlooking the golf course."),
    ("Arabian Ranches Villa", "Arabian Ranches", 5200000, 4, 5, "Villa",
     "Sale", 3400, ["Private pool", "Garden", "Maid's room", "Security"],
     "Yes", "No", "Family villa on a quiet, landscaped street."),
    # --- Rentals ---
    ("Marina Manor 1-Bed (Rent)", "Dubai Marina", 90000, 1, 1, "Apartment",
     "Rent", 780, ["Swimming pool", "Gym", "Nearby metro"], "Yes", "Yes",
     "Furnished 1-bedroom available for annual lease."),
    ("Downtown Executive 2-Bed (Rent)", "Downtown Dubai", 165000, 2, 3, "Apartment",
     "Rent", 1260, ["Swimming pool", "Gym", "Covered parking", "Nearby metro"],
     "Yes", "Yes", "Executive 2-bedroom rental near DIFC."),
    ("JLT Studio (Rent)", "Jumeirah Lakes Towers", 60000, 0, 1, "Studio",
     "Rent", 500, ["Gym", "Nearby metro"], "No", "Yes",
     "Well-kept studio close to the metro in JLT."),
    ("Business Bay 2-Bed (Rent)", "Business Bay", 125000, 2, 2, "Apartment",
     "Rent", 1120, ["Swimming pool", "Gym", "Covered parking", "Balcony"],
     "Yes", "No", "Canal-view 2-bedroom in Business Bay."),
    ("The Springs Villa (Rent)", "The Springs", 220000, 3, 3, "Villa",
     "Rent", 2400, ["Private pool", "Garden", "Security"], "Yes", "No",
     "3-bedroom villa with garden, pet-friendly."),
]


def seed_demo_properties(verbose=True):
    """Insert the demo listings once. Returns the number of rows added."""
    init_db()
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE is_demo = 1"
        ).fetchone()[0]
        if existing:
            if verbose:
                print(f"ℹ️  {existing} demo listings already present — skipping.")
            return 0

        for row in DEMO_PROPERTIES:
            (name, location, price, bedrooms, bathrooms, property_type,
             listing_purpose, area_sqft, amenities, pool, metro, description) = row
            conn.execute(
                """
                INSERT INTO properties
                    (name, location, price, bedrooms, bathrooms, property_type,
                     listing_purpose, area_sqft, amenities, has_swimming_pool,
                     nearby_metro, status, description, currency, is_demo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Available', ?, ?, 1)
                """,
                (name, location, price, bedrooms, bathrooms, property_type,
                 listing_purpose, area_sqft, json.dumps(amenities), pool,
                 metro, description, "AED"),
            )
        conn.commit()
        if verbose:
            print(f"✅ Seeded {len(DEMO_PROPERTIES)} demo listings "
                  f"(Sale + Rent, is_demo = 1).")
        return len(DEMO_PROPERTIES)
    finally:
        conn.close()


if __name__ == "__main__":
    added = seed_demo_properties()
    print(f"📊 Demo listings added this run: {added}")
