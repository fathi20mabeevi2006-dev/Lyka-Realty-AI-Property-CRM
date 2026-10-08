import csv
import sqlite3

DB_FILE = "crm.db"
CSV_FILE = r"C:\Users\admin\Downloads\dubai dataset\realestatedata.csv"

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

print("Deleting existing properties...")
cursor.execute("DELETE FROM properties")

print("Importing Dubai dataset...")

count = 0

with open(CSV_FILE, "r", encoding="utf-8") as file:
    reader = csv.DictReader(file)

    for row in reader:
        try:
            name = row.get("apart.area.name", "Property")
            location = row.get("area.name", "Dubai")

            price = float(row.get("price", 0))

            beds = row.get("no.beds", 0)
            beds = int(float(beds)) if beds else 0

            size = row.get("size.sq.meter", "")

            cursor.execute("""
                INSERT INTO properties
                (
                    name,
                    location,
                    price,
                    bedrooms,
                    bathrooms,
                    floor_number,
                    property_view,
                    has_swimming_pool,
                    nearby_metro,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                location,
                price,
                beds,
                1,
                0,
                f"Size: {size} sqm",
                "No",
                "No",
                "Available"
            ))

            count += 1

        except Exception:
            pass

conn.commit()
conn.close()

print(f"Imported {count} properties successfully!")