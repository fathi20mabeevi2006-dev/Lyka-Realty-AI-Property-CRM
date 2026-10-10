# 🏠 PropAI — AI-Powered Property CRM

A beginner-friendly **real estate CRM** web app built with **HTML, CSS, JavaScript**, **Python Flask**, and **SQLite**.  
It includes property management, lead tracking, a responsive dashboard, and an **AI Assistant** that answers questions using your own CRM data.

---

## ✨ Features

| Module | What it does |
|--------|--------------|
| **Dashboard** | Total / Available / Sold / Rented properties + total leads, with recent activity |
| **Properties** | Add, edit, delete, a **details page** per property, **advanced filters** (location, price, beds, baths, pool, metro, view, status) applied instantly, and **multi-image upload** with gallery + list thumbnails. Stores name, location, price, bedrooms, bathrooms, **floor number, property view, swimming pool (Y/N), nearby metro (Y/N)**, status |
| **Leads & Clients** | Add, edit, delete clients with budget, location, requirements & status. **Lead detail** page shows requirements, qualification score + priority, status history, and follow-up notes |
| **AI Lead Analysis** | Paste a free-text enquiry at `/leads/analyse`; the backend extracts structured requirements (beds, budget, location, amenities, timeline), flags missing information with clarification questions, and saves it as a new lead. Uses `openai → groq → offline` providers with strict schema validation. **Never invents values** and never presents the offline fallback as live AI |
| **Qualification & Matching** | Every lead gets a transparent 0–100 qualification score with a high/medium/low priority and a per-rule breakdown. One click generates **top-3 property recommendations** from your real listings, with match score, reasons and mismatches — honest "no match" when nothing fits |
| **AI Assistant** | Chat page whose answers are **grounded in your live CRM database**. Uses the Groq LLM when `GROQ_API_KEY` is set, and automatically falls back to the built-in offline rule-based answers if Groq is missing or unreachable. Searches by city, bedrooms, pool, metro, price & status |
| **Business Analysis** | Record your company profile, business model, objectives, customers, workflows, software, challenges and risks as **facts, assumptions and recommendations** with category/source/status filters |
| **Requirements & Gap Analysis** | Track functional / non-functional requirements with priority, status, owner, acceptance criteria, dependencies and risks. Compare **current state vs desired state** to automatically flag gaps, sorted by priority |
| **BRD Generator** | One-click **Business Requirements Document** built from your Business Analysis notes + Requirements. Splits facts, assumptions and recommendations, adds business objectives, problems, proposed solutions, priorities and acceptance criteria, and marks anything missing as "not documented" — it never invents facts. Live preview at `/brd`, PDF download at `/brd/export` |
| **UI** | Professional dashboard, sidebar navigation, responsive on mobile |

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

This installs Flask, the optional Groq AI client, python-dotenv, and `fpdf2`
(used by the BRD Generator's PDF export). If `fpdf2` is not installed, the BRD
preview still works — only the Download button shows a friendly message.

### 2. Configure your `.env`

Create a `.env` file in the project root (it is git-ignored):

```
# Optional — if omitted, the offline assistant is used automatically
GROQ_API_KEY=your_groq_key_here

# Optional — random session secret (auto-generated if missing)
SECRET_KEY=any_long_random_string

# Optional — display currency label (stored prices never change)
CURRENCY=AED
```

### 3. (Optional) Load sample data

```bash
python seed_data.py
```

This adds 18 sample properties and 8 sample leads so the dashboard and AI Assistant have something to show.

To try the **property matching** engine, also load the clearly-labelled demo
listings (both Sale and Rent, marked `is_demo = 1`):

```bash
python seed_demo_properties.py
```

It is idempotent and additive — it never touches your imported rows. Remove them
any time with `DELETE FROM properties WHERE is_demo = 1`.

See `.env.example` for the full list of supported environment variables
(OpenAI/Groq keys, models, timeouts and rate limits).

### 4. Run the app

```bash
python app.py
```

### 5. Open in your browser

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
├── config.py              # Loads SECRET_KEY, CURRENCY, GROQ_API_KEY from .env
├── ai_assistant.py        # DB-grounded offline assistant (+ AI context builder)
├── brd.py                 # BRD document model (single source of truth)
├── services/
│   ├── groq_service.py    # Optional Groq LLM with offline fallback
│   └── pdf_exporter.py    # BRD -> PDF (fpdf2; degrades gracefully if missing)
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
    ├── assistant.html        # AI chat interface
    ├── business_analysis.html        # Business Analysis list + filters
    ├── business_analysis_form.html   # Add / Edit business note
    ├── requirements.html             # Requirements list + filters
    ├── requirements_form.html        # Add / Edit requirement
    ├── gap_analysis.html             # Current vs desired state comparison
    └── brd.html                      # BRD preview (live document)
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
    ↓ get_ai_response(message)          services/groq_service.py
    ↓   grounding_context(message)      ai_assistant.py  → real SQL facts
    ↓   (Groq LLM answers, using ONLY those facts)   ← if GROQ_API_KEY is set
    ↓   answer_question(message)         ai_assistant.py → offline rule-based
    ↓                                    ← automatic fallback if Groq is off/fails
SQLite (crm.db)
    ↓ results
Human-readable answer rendered back to the chat
```

The assistant never invents data: when the Groq key is present it is given a
verified block of CRM facts and told to answer only from those. If the key is
missing or the API call fails, it uses the offline rule-based answers instead.
Customer phone numbers and emails are deliberately excluded from AI context.

---

## 📄 BRD Generator

The **Business Requirements Document** is generated automatically (read-only —
it never writes to the database) from what you have recorded in **Business
Analysis** and **Requirements**:

- Open the live preview: `http://127.0.0.1:5000/brd`
- Download the PDF: `http://127.0.0.1:5000/brd/export`

The document contains:

1. **Current State (Verified Facts)** — live counts (properties, leads) and
   portfolio value, each with a note explaining exactly how it was computed,
   timestamped with when it was collected.
2. **Company Profile** and **Business Objectives** — from the matching
   Business Analysis categories.
3. **Documented Facts / Assumptions / Recommendations** — separated by source
   type.
4. **Identified Business Problems** and **Proposed Solutions** — from
   requirements.
5. **Functional & Non-Functional Requirements** — grouped by type, sorted by
   priority, with acceptance criteria where documented.
6. **Gap Analysis Summary** — gaps flagged by the Gap Analysis module.
7. **Missing Information** — anything not documented is listed honestly,
   never invented.

The preview (`brd.html`) and the PDF (`services/pdf_exporter.py`) both render
the same `build_brd()` model from `brd.py`, so they can never disagree. The
PDF export only needs the pure-Python `fpdf2` package; if it's missing, the
app shows a message and the preview keeps working.

---

## 🗄 Database Schema

**properties**
```
id, name, location, price, bedrooms, bathrooms, floor_number,
property_view, has_swimming_pool, nearby_metro, status,
property_type, property_size, created_at, updated_at
```

**leads**
```
id, client_name, phone, email, budget, preferred_location,
bedrooms_needed, needs_swimming_pool, needs_nearby_metro,
status, notes, lead_source, assigned_to, next_follow_up,
last_contact, lead_score, created_at, updated_at
```

**property_images**
```
id, property_id, filename, uploaded_at
```

**business_analysis** (Phase 3 — Planning & Strategy)
```
id, category, title, details, source_type, status,
created_by (default 'local'), created_at, updated_at
```
`category` uses a fixed whitelist (Company Profile, Business Model, Objectives, Target Customers, …) and `source_type` is one of `Fact`, `Assumption`, `Recommendation`.

**requirements** (Phase 3 — Planning & Strategy)
```
id, title, description, problem, proposed_solution, req_type,
category, priority, status, owner, acceptance_criteria,
dependencies, risks, current_state, desired_state, gap_notes,
created_by (default 'local'), created_at, updated_at
```
`req_type` is `Functional` / `Non-Functional`; `priority` is `High` / `Medium` / `Low`; `status` is `Draft` / `Approved` / `In Progress` / `Done` / `Deferred`.

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

Later additions (still additive, older databases upgrade automatically):
`property_type` (text), `property_size` (real, sqm) and `updated_at` on both
`properties` and `leads`.

Phase 3 additions are strictly **new tables only** (`business_analysis`,
`requirements`) via `CREATE TABLE IF NOT EXISTS` — existing tables are never
modified again. Invalid choice values (category, source type, priority,
status…) are silently corrected to their safe defaults on write.

---

## 🛠 Tech Stack

- **Frontend:** HTML5, CSS3 (custom responsive design), vanilla JavaScript
- **Backend:** Python 3 + Flask
- **Database:** SQLite (no server setup needed)
- **Fonts:** Google Fonts (Inter)

---

## 💡 Ideas to Extend

- Match leads to properties automatically (budget + location + bedrooms)
- Export properties/leads and the BRD to CSV / PDF / DOCX
- User login & authentication
- Replace the rule-based assistant with a real LLM API
- Add appointment/viewing scheduling

---

Built for learning. Happy coding! 🚀
