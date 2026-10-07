"""
seed_data.py
Adds sample properties and leads so the dashboard and AI Assistant
have data to work with right away. Safe to run multiple times -
it only seeds when the tables are empty.
"""

import sys

# Windows terminals (cp1252) can't print emoji — switch to UTF-8 safely
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from database import init_db, get_connection, get_all_properties, get_all_leads


SAMPLE_PROPERTIES = [
    # Dubai
    ("Marina View Penthouse", "Dubai Marina, Dubai", 25000000, 3, 4, 22, "Sea View", "Yes", "Yes", "Available"),
    ("Palm Jumeirah Villa", "Palm Jumeirah, Dubai", 45000000, 5, 6, 1, "Beach View", "Yes", "No", "Sold"),
    ("Downtown Skyline Apartment", "Downtown Dubai, Dubai", 18000000, 2, 3, 15, "City View", "Yes", "Yes", "Available"),
    ("JLT Studio Loft", "Jumeirah Lakes Towers, Dubai", 4500000, 1, 1, 9, "Lake View", "No", "Yes", "Available"),
    ("Business Bay Apartment", "Business Bay, Dubai", 9500000, 2, 2, 12, "Canal View", "Yes", "Yes", "Rented"),
    # Chennai
    ("OMR Tech Park Flat", "OMR, Chennai", 12000000, 3, 3, 7, "City View", "Yes", "Yes", "Available"),
    ("Adyar Family Home", "Adyar, Chennai", 15500000, 4, 4, 2, "Garden View", "Yes", "No", "Available"),
    ("Velachery 2BHK", "Velachery, Chennai", 8200000, 2, 2, 5, "City View", "No", "Yes", "Available"),
    ("Anna Nagar Tower", "Anna Nagar, Chennai", 11000000, 3, 3, 18, "Pool View", "Yes", "Yes", "Sold"),
    ("T. Nagar Studio", "T. Nagar, Chennai", 3800000, 1, 1, 3, "Market View", "No", "No", "Rented"),
    # Mumbai
    ("Bandra Sea Facing", "Bandra West, Mumbai", 55000000, 4, 5, 20, "Sea View", "Yes", "Yes", "Available"),
    ("Andheri Smart Home", "Andheri East, Mumbai", 22000000, 3, 3, 11, "City View", "Yes", "Yes", "Available"),
    ("Powai Lake Villa", "Powai, Mumbai", 32000000, 4, 4, 0, "Lake View", "Yes", "Yes", "Sold"),
    ("Dadar Compact Flat", "Dadar, Mumbai", 14500000, 2, 2, 6, "City View", "No", "Yes", "Available"),
    # Bangalore
    ("Whitefield Villa", "Whitefield, Bangalore", 28000000, 4, 4, 0, "Garden View", "Yes", "Yes", "Available"),
    ("Koramangala Apartment", "Koramangala, Bangalore", 16500000, 3, 3, 10, "City View", "Yes", "Yes", "Available"),
    ("HSR Layout Flat", "HSR Layout, Bangalore", 9800000, 2, 2, 8, "City View", "No", "No", "Available"),
    ("Indiranagar Loft", "Indiranagar, Bangalore", 12500000, 2, 2, 4, "Street View", "No", "Yes", "Rented"),
]


SAMPLE_LEADS = [
    ("Rahul Sharma", "+91 98765 43210", "rahul.sharma@email.com", 20000000, "Dubai", 2, "Yes", "Yes", "Contacted", "Looking for a 2BHK in Dubai Marina with pool."),
    ("Priya Nair", "+91 99887 76655", "priya.nair@email.com", 16000000, "Chennai", 3, "Yes", "Yes", "New", "Family of 4, wants OMR or Adyar."),
    ("Amit Patel", "+91 90012 34567", "amit.patel@email.com", 30000000, "Mumbai", 4, "No", "Yes", "Qualified", "Sea-facing preferred in Bandra or Powai."),
    ("Sneha Iyer", "+91 91234 56789", "sneha.iyer@email.com", 12000000, "Bangalore", 3, "Yes", "Yes", "Contacted", "First-time buyer, needs metro connectivity."),
    ("Vikram Singh", "+91 98989 98989", "vikram.singh@email.com", 40000000, "Dubai", 4, "Yes", "No", "New", "Investor, interested in Palm Jumeirah."),
    ("Ananya Reddy", "+91 97654 32109", "ananya.reddy@email.com", 9000000, "Chennai", 2, "No", "Yes", "New", "Budget-friendly 2BHK near metro."),
    ("Karan Mehta", "+91 93456 78901", "karan.mehta@email.com", 25000000, "Bangalore", 3, "Yes", "Yes", "Closed", "Bought Koramangala apartment."),
    ("Divya Menon", "+91 92345 67890", "divya.menon@email.com", 18000000, "Chennai", 3, "Yes", "Yes", "Qualified", "Ready to buy within a month."),
]


def seed():
    init_db()
    conn = get_connection()

    if conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0] == 0:
        conn.executemany(
            """
            INSERT INTO properties
                (name, location, price, bedrooms, bathrooms, floor_number,
                 property_view, has_swimming_pool, nearby_metro, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            SAMPLE_PROPERTIES,
        )
        print(f"✅ Seeded {len(SAMPLE_PROPERTIES)} sample properties.")
    else:
        print("ℹ️  Properties table already has data — skipping property seed.")

    if conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0:
        conn.executemany(
            """
            INSERT INTO leads
                (client_name, phone, email, budget, preferred_location,
                 bedrooms_needed, needs_swimming_pool, needs_nearby_metro,
                 status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            SAMPLE_LEADS,
        )
        print(f"✅ Seeded {len(SAMPLE_LEADS)} sample leads.")
    else:
        print("ℹ️  Leads table already has data — skipping lead seed.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed()
    print(f"📊 Properties in DB: {len(get_all_properties())}")
    print(f"👤 Leads in DB: {len(get_all_leads())}")
