# Architecture — Lyka Realty AI Property CRM

## 1. Stack (unchanged)

- **Backend:** Flask 3, Jinja2 templates, Python 3.13.
- **Frontend:** server-rendered Jinja + vanilla JS (no Node/React).
- **Database:** SQLite (`crm.db`) accessed through `database.py` helper functions.
- **AI:** provider abstraction over the official OpenAI and Groq SDKs, with a
  deterministic offline fallback.

## 2. Request → AI → storage flow

```
Browser form / fetch
      │
      ▼
app.py route  ── permission + CSRF + rate limit ──►  services.ai_extract.analyse_enquiry
                                                          │  provider chain
                                                          │  openai → groq → offline
                                                          ▼
                                                   services.lead_schema.validate_extraction
                                                          │  (strict, never invents)
                                                          ▼
                                        validated fields + missing info + questions
                                                          │
                     ┌────────────────────────────────────┴───────────────┐
                     ▼                                                     ▼
            services.qualification.score_lead                     (on save) database.add_lead
                     │  score / priority / breakdown                        │
                     └───────────────────► database.add_lead ◄──────────────┘
                                                          │
                                                          ▼
                                             services.matching.match_properties
                                                          │  hard filters + weighted score
                                                          ▼
                                             database.save_recommendations
                                                          ▼
                                       recommendations / lead_notes / lead_status_history
```

## 3. Modules

| Module | Responsibility |
|---|---|
| `services/lead_schema.py` | Canonical extraction schema; `validate_enquiry` (raises), `validate_extraction` (never raises), `derive_missing_and_questions`. |
| `services/ai_extract.py` | Provider selection, prompt with untrusted-data delimiting, timeout + one retry, JSON parsing, offline fallthrough, `provider_status()` (booleans only). |
| `services/offline_extract.py` | Deterministic rule-based extractor — always available, always flagged `degraded`. |
| `services/qualification.py` | PRD rule-based 0–100 score with High/Medium/Low priority and a per-rule breakdown. |
| `services/matching.py` | Purpose/availability hard filters, location hard-exclusion, weighted scoring, top-3 results with reasons/mismatches, honest no-match. |
| `database.py` | All persistence; additive migrations; CRUD for leads, notes, history, recommendations, dashboard stats. |
| `app.py` | Routes, RBAC gates, CSRF, rate limiting, JSON APIs. |

## 4. Data model additions (all additive)

New / extended `leads` columns: `lead_type, property_type, bathrooms_needed, budget_min,
budget_max, currency, purpose, amenities, timeline_days, timeline_label, missing_fields,
score_breakdown, priority, raw_enquiry, analysis_provider, analysed_at` (plus existing
`lead_score`).

New `properties` columns: `listing_purpose, amenities, currency, area_sqft, description,
building_name, agent_name, is_demo`.

New tables:

- `lead_notes (id, lead_id, author, body, created_at)`
- `lead_status_history (id, lead_id, from_status, to_status, changed_by, created_at)`
- `recommendations (id, lead_id, property_id, match_score, reasons, mismatches, snapshot,
  engine_version, created_at)`

Migration path: `init_db() → backup_db() → _ensure_columns() → CREATE TABLE IF NOT EXISTS`.
No `DROP`, no data rewrite. Existing statuses remain readable.

## 5. Security

- Sessions, RBAC (8 roles), CSRF (global `before_request`), audit log, rate limiting.
- API keys read server-side only; never serialised to the client; `provider_status`
  exposes booleans/model names only.
- Customer text is passed as untrusted data inside `<enquiry>` delimiters; the system
  prompt forbids instruction-following and invention.

## 6. Key decisions

| ID | Decision |
|---|---|
| ARCH-01 | Keep Flask/Jinja/SQLite (PRD's Node/React/PostgreSQL are optional). |
| ARCH-02 | Provider chain `openai → groq → offline`, always schema-validated. |
| ARCH-03 | Additive DB changes only, with backup first. |
| ARCH-04 | Offline analysis is never presented as live AI (`degraded=True`). |
| ARCH-05 | A stated location with zero overlap is a hard exclusion (location is the highest weight). |
