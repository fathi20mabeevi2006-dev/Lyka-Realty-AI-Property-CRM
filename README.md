# 🏠 PropAI — AI-Powered Property CRM

A beginner-friendly **real estate CRM** web app built with **HTML, CSS, JavaScript**, **Python Flask**, and **SQLite**.  
It includes property management, lead tracking, a responsive dashboard, and an **AI Assistant** that answers questions using your own CRM data.

---

## ✨ Features

| Module | What it does |
|--------|--------------|
| **Dashboard** | Total / Available / Sold / Rented properties + total leads, with recent activity |
| **Properties** | Add, edit, delete, a **details page** per property, **advanced filters** (location, price, beds, baths, pool, metro, view, status) applied instantly, and **multi-image upload** with gallery + list thumbnails. Stores name, location, price, bedrooms, bathrooms, **floor number, property view, swimming pool (Y/N), nearby metro (Y/N)**, status |
| **Leads & Clients** | Add, edit, delete clients with budget, location, requirements & status |
| **AI Assistant** | Chat page that reads live data from SQLite — searches by city, bedrooms, **floor, view**, pool & metro, and counts filtered results |
| **UI** | Professional dashboard, sidebar navigation, responsive on mobile |

---

## 🚀 Quick Start

### 1. Install Flask

```bash
pip install -r requirements.txt
```

### 2. (Optional) Load sample data

```bash
python seed_data.py
```

This adds 18 sample properties and 8 sample leads so the dashboard and AI Assistant have something to show.

### 3. Run the app

```bash
python app.py
```

### 4. Open in your browser

```
http://127.0.0.1:5000
```

---

## 🗂 Project Structure

```
AI-Property-CRM/
│
├── app.py                 # Flask app — routes for pages + JSON API
├── database.py            # All SQLite operations (CRUD + stats)
├── ai_assistant.py        # Rule-based AI that queries the database
├── seed_data.py           # Sample properties & leads
├── requirements.txt       # Python dependencies
├── crm.db                 # SQLite database (created automatically)
│
├── static/
│   ├── css/style.css      # Full dashboard styling + responsive design
│   ├── uploads/properties/ # Uploaded property images (auto-created)
│   └── js/
│       ├── main.js        # Sidebar toggle, flash messages
│       ├── filters.js     # Instant property filtering
│       └── assistant.js   # Chat UI logic
│
└── templates/
    ├── base.html             # Sidebar + topbar layout
    ├── dashboard.html        # Stats + recent items
    ├── properties.html       # Property table
    ├── property_form.html    # Add / Edit property
    ├── property_detail.html  # Property details page (specs + gallery)
    ├── leads.html            # Leads table
    ├── lead_form.html        # Add / Edit lead
    └── assistant.html        # AI chat interface
```

---

### 📷 Property images

- Upload **multiple images** (JPG, PNG, GIF, WEBP) when adding or editing a property
- Max **10 MB per request**; filenames are regenerated with UUIDs (client names never trusted)
- Images are stored in `static/uploads/properties/`; paths live in the `property_images` table
- **Gallery** with click-to-open on the details page; **thumbnail** in the property list
- Delete photos from the **Edit page** (✕ button); deleting a property removes its files too

### 🔍 Property search filters

The **Properties** page filter panel supports:

| Filter | Match |
|--------|-------|
| Search box | name or location (substring) |
| Location | location only (substring) |
| Status / Pool / Metro | exact (Any / Yes / No) |
| Min / Max price | inclusive range |
| Bedrooms / Bathrooms | exact count |
| Property View | exact view, or "None" |

Results update **instantly** while you type/change (`static/js/filters.js`),
and the same filters work server-side as plain GET parameters — so filtered
URLs are shareable and the page still works with JavaScript disabled.

Example: `/properties?location=Dubai&min_price=5000000&bedrooms=2&pool=Yes`

---

## 🤖 AI Assistant Examples

The assistant reads **live data** from `crm.db`. Try these in the chat:

- `Show me properties with a swimming pool.`
- `Show me properties near a metro station.`
- `Show me sea-view properties.`
- `Show me properties on the 15th floor.`
- `Show me 2-bedroom properties in Dubai with swimming pool.`
- `How many properties are sold?`
- `Show available properties in Chennai.`
- `How many properties have a swimming pool?`
- `How many leads do I have?`
- `Give me stats`
- `List all properties`

### How it works

```
Browser (assistant.js)
    ↓ POST { message }
Flask  /api/assistant  (app.py)
    ↓ answer_question(message)
ai_assistant.py  →  parses city / bedrooms / pool / metro / status
    ↓ SQL queries
SQLite (crm.db)
    ↓ results
Human-readable answer rendered back to the chat
```

Everything runs **offline** — no external AI API or internet required.  
The parsing is intentionally simple and readable so you can later swap it for OpenAI/Gemini without touching the rest of the app.

---

## 🗄 Database Schema

**properties**
```
id, name, location, price, bedrooms, bathrooms, floor_number,
property_view, has_swimming_pool, nearby_metro, status, created_at
```

**leads**
```
id, client_name, phone, email, budget, preferred_location,
bedrooms_needed, needs_swimming_pool, needs_nearby_metro,
status, notes, created_at
```

**property_images**
```
id, property_id, filename, uploaded_at
```

### 🔄 Automatic migrations

On startup, `database.py` checks the schema of the existing `crm.db` and
adds any missing columns with `ALTER TABLE ... ADD COLUMN`. This means:

- **Older databases upgrade in place** — no need to delete `crm.db`.
- Existing rows are kept; new columns are filled with safe defaults
  (`No` for pool/metro, `NULL` for floor/view).
- Writes are normalized: pool/metro are stored only as `Yes` or `No`,
  and the status is validated to `Available` / `Sold` / `Rented`.

The Phase 1 fields are:
`floor_number` (int, 0 = ground), `property_view` (text),
`has_swimming_pool` (`Yes`/`No`), `nearby_metro` (`Yes`/`No`).

---

## 🛠 Tech Stack

- **Frontend:** HTML5, CSS3 (custom responsive design), vanilla JavaScript
- **Backend:** Python 3 + Flask
- **Database:** SQLite (no server setup needed)
- **Fonts:** Google Fonts (Inter)

---

## 💡 Ideas to Extend

- Match leads to properties automatically (budget + location + bedrooms)
- Add images for properties
- Export properties/leads to CSV
- User login & authentication
- Replace the rule-based assistant with a real LLM API
- Add appointment/viewing scheduling

---

Built for learning. Happy coding! 🚀
