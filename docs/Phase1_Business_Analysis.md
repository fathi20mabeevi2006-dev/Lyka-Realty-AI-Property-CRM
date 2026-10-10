# Lyka Realty AI ERP — Phase 1 Business Analysis & Requirements Document

Prepared by: Solution Architect (Phase 1 review)
Date: 2026-10-10
Applies to: `AI-Property-CRM` (Flask + SQLite)

This document is the **phase 1 deliverable**. No code was changed to produce it.
It is a read-only review of the existing application and a blueprint for the
ERP transformation. Sections: feature inventory, current architecture, BRD,
role-permission matrix, proposed database schema, security assessment, phased
implementation plan, and business questions that need owner approval.

---

## 1. Existing feature inventory (verified)

The app already works and is used with real data. Verified on 2026-10-10:

| Area | What exists today |
|---|---|
| **Dashboard** (`/`) | Property totals (available/sold/rented), total leads, portfolio value, average price, location + bedroom distributions, lead-status summary, recent properties (6), recent leads (5), due/overdue follow-ups (6) |
| **Properties** | Full CRUD, detail page with image gallery, multi-image upload (JPG/PNG/GIF/WEBP, 10 MB request cap, UUID filenames), list thumbnails, advanced filters + instant client-side search, fields: name, location, price, bedrooms, bathrooms, floor, view, pool, metro, status, type, size |
| **Leads / Clients** | Full CRUD, budget, requirements (location/beds/pool/metro), source, `assigned_to`, `next_follow_up`, `last_contact`, auto lead-score (0–100, transparent rules), pipeline statuses (New/Contacted/Qualified/Closed/Lost), quick-status dropdown, filters (status, text, source, follow-up state, min score, budget range) |
| **AI Assistant** (`/assistant`) | DB-grounded chat. Uses Groq LLM when `GROQ_API_KEY` is set, offline rule-based answers otherwise. Contractor grounding payload explicitly excludes customer phone/email. Returns property lists, counts, stats |
| **Business Analysis** | Notes with category/type (Fact/Assumption/Recommendation)/status whitelists + filters |
| **Requirements & Gap Analysis** | Functional/non-functional requirements with priority, status, owner, acceptance criteria, dependencies, risks; auto gap flag from current vs desired state |
| **BRD Generator** (`/brd`, `/brd/export`) | `build_brd()` model rendered identically in HTML and PDF (fpdf2); explicitly reports "not documented" instead of inventing facts |
| **UI shell** | Single `base.html` sidebar layout, responsive CSS, brand/logo, flash messages, skip-link |

**Live database state (crm.db):**

| Table | Rows |
|---|---|
| properties | 6,514 (Dubai import; all status "Available"; `bathrooms=1`, view = "Size: … sqm" quirks from import; locations have a leading space) |
| leads | 9 |
| property_images | 1 |
| business_analysis | 1 |
| requirements | 1 |

**Test status:** 37 `unittest` tests in `tests/` all pass, each running against a
disposable copy of the DB (never the real one). Note: the root-level files
`_test_phase1.py`, `_test_phase2.py`, `_test_images.py` are **stale legacy
scripts** (they assert 20 properties / 8 leads) and are not part of the
maintained suite; they should be retired or updated, not treated as a spec.

---

## 2. Current architecture

**Stack (kept from the original project):** Python 3 + Flask, SQLite
(`crm.db`), Jinja2 templates, vanilla JavaScript, custom CSS. External libs:
`groq`, `python-dotenv`, `fpdf2` (`requirements.txt`).

```
browser (Jinja2 + JS)
   │
   └─ app.py (all routes: pages + JSON API)          ← presentation + routing
        │
        ├─ database.py (sqlite3 CRUD + analytics)    ← data layer, no raw SQL in app
        │     └─ crm.db (SQLite, auto-migrated on startup)
        │
        ├─ services/groq_service.py                  ← LLM w/ offline fallback
        │     └─ ai_assistant.py                     ← grounding + rule answers
        ├─ brd.py                                    ← BRD document model
        └─ services/pdf_exporter.py                  ← BRD → PDF
```

**Key properties:**

- No packages; functions in `app.py` (720 lines) and `database.py` (992 lines).
- All SQL is parameterized; Jinja autoescape is on (no `| safe` anywhere).
- Migrations are additive: missing columns on `properties`/`leads` are added
  with `ALTER TABLE`; new tables use `CREATE TABLE IF NOT EXISTS`. Existing
  data is preserved.
- Filtering is done **in Python memory** on full-table reads (e.g.
  `get_all_properties()` then list-comprehension filters), and duplicated by
  `filters.js` on the client. No SQL `LIMIT`/`OFFSET` pagination; no indexes.
- Write values are normalized (yes/no, status whitelists), with some gaps (see
  Security Assessment §6).
- Config comes from `.env` (git-ignored) via `config.py`. `SECRET_KEY`,
  `GROQ_API_KEY`, `CURRENCY` are set.

**Business workflows today** (as implemented): list/search properties →
view/detail → edit/delete; capture lead → assign + schedule follow-up →
change status → scored automatically; ask AI for property matches/stats;
record business notes/requirements → generate BRD. There is **no** deal
pipeline, sales/visit tracking, finance, HR, marketing campaign, approval
flow, client portal, or role-based access — this is the gap the ERP must fill.

---

## 3. Business Requirements Document (BRD) — summary

### 3.1 Business context (verified)
Lyka Realty operates an internal property CRM. It currently holds one large
Dubai listing dataset (6,514 records) plus a small lead book (9). All existing
pages are open to anyone who can reach the server. The conversion target is a
company-wide, role-aware ERP used by several departments and external clients.

### 3.2 Objectives
1. Preserve all working functionality, records, images, and git history.
2. Add secured authentication and role-based access control (Phase 2).
3. Add departmental ERP modules one at a time (Phase 3).
4. Add controlled AI agents that only use verified data (Phase 4).
5. Harden the technical base (tests, indexes, logging, config) (Phase 5).

### 3.3 Functional scope (mapped to the project brief)
- Authentication & access control: users, roles, login/logout, sessions,
  password hashing, account management, per-role dashboards, backend
  enforcement, audit log.
- ERP modules: property/project management; CRM + lead assignment; sales
  pipeline, follow-ups, site visits, deals; marketing campaigns + lead-source
  analytics; finance (invoices, receipts, payment schedules, commissions);
  HR; operations & maintenance; client portal & document access; management
  reports, notifications, approvals.
- AI: property matching, follow-up suggestions, business reporting,
  missing-data detection, customer support, internal knowledge retrieval —
  always tool-based, validated data, human confirmation for sensitive actions.

### 3.4 Non-functional requirements
- Security: backend-enforced RBAC; CSRF-safe forms; hashed passwords; no
  secrets in code; audit trail for important changes.
- Data integrity: transactional writes; additive migrations; backup before
  any migration; no overwrites of existing records.
- Maintainability: modular Flask services; one responsibility per module;
  documentation of each data model and permission matrix before coding.
- Performance: appropriate SQL indexes and pagination once modules are added.
- Testing: automated tests for every module; suite must stay green.

### 3.5 Out of scope for Phase 1
Full rebuild, cloud deployment, replacing SQLite, erasing or restructuring
existing data, real-customer demo data without authorisation.

---

## 4. Role-permission matrix (proposed)

L = view/list, A = add, E = edit, D = delete, O = approve/confirm, X = none.

| Module | Super Admin | Company Admin / Mgmt | Sales / CRM | Marketing | Finance / Accounts | HR / Employees | Property / Ops | Client / Customer |
|---|---|---|---|---|---|---|---|---|
| Dashboard (own dept. view) | L, all | L | L | L | L | L | L | L (limited) |
| Global dashboard / reports | L,A | L | X | X | X | X | X | X |
| Users & roles | A,E,D | L,E (staff) | X | X | X | X | X | X |
| Properties (catalogue) | L,A,E,D | L,A,E | L | L | L | L | L,A,E | L |
| Property status change / sale | O | O | E (propose) | X | X | X | E (list/update) | X |
| Leads (all) | L,A,E,D | L | L | L | X | X | X | L (own data only) |
| Leads (own assignment) | L,A,E,D | L | A,E (own) | A (campaign leads) | X | X | X | X |
| Sales pipeline / deals | L | L,O | A,E | X | L | X | X | L (own deal) |
| Follow-ups & site visits | L | L | A,E | X | X | X | X | X |
| Marketing campaigns | L | L,O | L | A,E | L | X | X | X |
| Invoices / receipts | L | L | X | X | A,E,D | X | L | L (own docs) |
| Payment schedules / commissions | L | L,O | L (own) | X | A,E | X | X | L (own) |
| HR / employees | L | L,E | X | X | L | A,E (self) | X | X |
| Operations & maintenance | L | L,O | X | X | L | X | A,E,D | X (request) |
| Client portal & documents | L | L | L | X | L | X | L | L,A (own) |
| Approvals workflow | O | O | E (request) | E (request) | E (request) | E (request) | E (request) | X |
| Notifications | O | L | L | L | L | L | L | L (own) |
| Audit log | L,A,E | L | X | X | X | X | X | X |
| AI assistant (verified data) | L | L | L | L | L | L | L | L (own scope) |
| AI sensitive actions (delete/approve) | O | O | proposed → human O | proposed → human O | proposed → human O | proposed → human O | proposed → human O | X |

Rules to enforce on the **backend**, not just the UI:
- Clients see only records explicitly linked to them (own lead/deal/documents).
- Finance data and staff salaries are hidden from Sales/Marketing/Clients.
- Deletions and financial approvals always require a higher role + audit log.
- A user may hold multiple roles; permission = union of role permissions.

---

## 5. Proposed database schema (additive only — existing tables preserved)

Existing tables (unchanged unless additive migration is approved): `properties`,
`leads`, `property_images`, `business_analysis`, `requirements`.

New tables proposed in Phase 2/3 (all `CREATE TABLE IF NOT EXISTS`; every table
gets `created_at`/`updated_at`; soft-delete flag where useful):

```
users            id, username UNIQUE, email, password_hash, full_name, department,
                 status, last_login_at, created_at, updated_at
roles            id, name UNIQUE, description
user_roles       user_id FK, role_id FK            (multi-role support)
sessions         id, user_id FK, token_hash, expires_at, created_at
audit_log        id, user_id FK NULL, action, entity_type, entity_id,
                 details, ip_address, user_agent, created_at

deals            id, lead_id FK, property_id FK, title, stage, amount,
                 probability, expected_close_date, owner_id FK, status,
                 created_at, updated_at
activities       id, lead_id FK, user_id FK, kind (call/email/visit/note),
                 notes, due_at, done_at, outcome, created_at
site_visits      id, deal_id FK NULL, lead_id FK, property_id FK,
                 scheduled_at, status (Scheduled/Done/Cancelled),
                 conducted_by FK, notes, created_at

marketing_campaigns id, name, channel, budget, start_date, end_date, status
marketing_leads  id, campaign_id FK, lead_id FK, source_detail, created_at

invoices         id, deal_id FK, lead_id FK, number UNIQUE, issue_date,
                 due_date, subtotal, tax, total, status, paid_amount, notes
payments         id, invoice_id FK, amount, method, received_date,
                 reference, recorded_by FK, created_at
payment_schedules id, deal_id FK, installment_no, due_date, amount,
                 status, created_at
commissions      id, deal_id FK, agent_id FK, base_amount, rate_percent,
                 amount, status, approved_by FK NULL, paid_at, created_at

employees        id, user_id FK, emp_code UNIQUE, department, job_title,
                 hire_date, salary, status
leave_requests   id, employee_id FK, start_date, end_date, type, reason,
                 status, reviewed_by FK NULL, reviewed_at, created_at

work_orders      id, property_id FK, kind (Maintenance/Repair/Inspection),
                 priority, description, status, assigned_to FK NULL,
                 due_at, cost, completed_at, created_at

notifications    id, user_id FK, kind, title, body, link, read_at, created_at
approvals        id, kind, entity_type, entity_id, requested_by FK,
                 status (Pending/Approved/Rejected), reviewed_by FK NULL,
                 reviewed_at, notes, created_at

client_documents id, lead_id FK, user_id FK (uploader), filename, category,
                 description, uploaded_at
knowledge_articles id, title, body, category, tags, updated_at (Phase 4)

ai_actions       id, agent, intent, payload, status (Draft/Proposed/Confirmed/
                 Executed/Rejected), created_by, decided_by FK NULL,
                 decided_at, created_at                (Phase 4 human-in-loop)
```

Relationships (core):
- `user_roles` → `users`, `roles`
- `deals` → `leads`, `properties`, `users`(owner)
- `site_visits`/`activities` → `leads`/`deals`
- `invoices` → `deals`/`leads`; `payments` → `invoices`; `payment_schedules`/`commissions` → `deals`
- `work_orders` → `properties`
- `audit_log`/`notifications` → `users`
- `approvals` polymorphic `entity_type`+`entity_id`

Indexes to add (Phase 5, non-destructive): `properties(location)`,
`properties(status)`, `properties(price)`, `leads(status)`,
`leads(next_follow_up)`, `leads(assigned_to)`, `property_images(property_id)`,
`audit_log(entity_type, entity_id)`, `invoices(number)`.

Data model decision per module must be approved **before** implementation.

---

## 6. Security assessment (current state)

Good practices already present:
- All SQL parameterised; no raw user input concatenated.
- Jinja autoescaping on; no `| safe`; assistant escapes chat HTML client-side.
- Uploaded files get UUID names + extension allowlist; filenames not trusted.
- AI grounding excludes phones/emails; offline fallback never invents data.
- Additive migrations; tests run against disposable DB copies.

| # | Severity | Finding |
|---|---|---|
| 1 | **Critical** | **No authentication/authorisation.** Every route (properties, leads incl. customer phone/email, business notes, requirements) is fully public — anyone can read/edit/delete. |
| 2 | **Critical** | **No audit log** for important changes; no record of who changed what. |
| 3 | **Critical** | `app.run(debug=True)` — in production debug mode exposes the Werkzeug console (remote code execution risk). |
| 4 | **High** | **No CSRF protection** on any POST form (property/lead/business/requirement delete + status updates). A forged form on another site can delete data. |
| 5 | **High** | No password hashing because no users exist yet; when added must use `werkzeug.security`/argon2, never plain text. |
| 6 | **High** | Assistant returns `f"Error: {str(e)}"` to the browser — leaks internals (and possibly the Groq key in provider error messages). Use generic client errors + server logging. |
| 7 | **High** | `SECRET_KEY` still has a hard-coded dev fallback (`property-crm-dev-key-change-me`) in `config.py`; if `.env` is missing on a server it becomes forgeable sessions. |
| 8 | **Medium** | File upload validates only the **extension**, not content (magic bytes). No per-file size limit (10 MB per request total). Serve uploads with `X-Content-Type-Options: nosniff`. |
| 9 | **Medium** | LLM prompt is built from user input + DB grounding. Grounding helps but is not a security boundary (`SYSTEM_PROMPT.format`). Treat the assistant as unprivileged; never let it execute actions in Phase 2/3 (Phase 4 uses a controlled tool layer). |
| 10 | **Medium** | No rate limiting on `/api/assistant` — allows cost/abuse amplification of the paid LLM API. |
| 11 | **Low** | `add_lead()` writes any `status` string (unlike property status, which is validated), so bogus statuses can corrupt pipeline counts. |
| 12 | **Low** | Latent bug in `brd.py` `brd_summary()` (and its `__main__` block) references `current_state["items"]` which does not exist — crashes if called. Not hit by the app today. |
| 13 | **Low** | `import_dubai_data.py` **deletes all properties** then imports from a hard-coded path; should be wrapped in backup/prompt and parameterised. |
| 14 | **Low** | ResourceWarnings during tests (unclosed SQLite connections in some raise/finally paths) — close connections consistently. |
| 15 | **Low** | Session cookie lacks `Secure`/`SameSite` config (dev HTTP); re-evaluate on deployment. |

---

## 7. Phased implementation plan

**Phase 1 — Review (this document).** Approval of BRD, permission matrix, and
schema before any code.

**Phase 2 — Authentication & access control.**
1. Back up `crm.db`; add additive schema (users, roles, user_roles, sessions,
   audit_log).
2. Users, password hashing (werkzeug), login/logout, session guard.
3. RBAC: permission checks enforced in backend (route-level), role-based
   dashboard + visibility, multi-role support.
4. CSRF tokens on all forms; secure config (no dev secret fallback, `debug=False` via env); upload magic-byte validation; generic API errors + logging.
5. Audit log writes on create/update/delete/status/login.
6. Lock down **everything** by default; super admin bootstrap account.
7. Tests: auth, RBAC matrix, CSRF, audit logging. Manual: every existing page with each role.

**Phase 3 — ERP modules** (each: data model + permissions + routes/templates + tests, one module at a time, app stays runnable after each).
3.1 Sales pipeline: deals, activities/follow-ups, site visits.
3.2 Marketing: campaigns, lead-source analytics, attribution.
3.3 Finance: invoices, receipts, payment schedules, commissions, client statements.
3.4 HR: employees, leave, department dashboards.
3.5 Operations: work orders/maintenance, property lifecycles (status changes with approvals).
3.6 Client portal: own-lead view, documents, status updates.
3.7 Reports, notifications, approvals workflow.
Backend enforcement for all reads/writes; audit + approval gates on finance/deletes.

**Phase 4 — AI agents.** Property matching, lead follow-up suggestions, business reporting, missing-data detection, customer support (scoped data), internal knowledge retrieval. All via authorised tools + validated backend data; human confirmation for deletions, financial actions, approvals, important status changes. `ai_actions` table records proposals/confirmations.

**Phase 5 — Technical quality.** Indexes, pagination, filtering in SQL,
transaction guards, structured logging, dependency of tests, backup-before-migration policy, retire stale `_test_phase*.py` scripts, revisit SQLite→PostgreSQL only if justified.

Each phase ends with: green test suite + honest report of unresolved issues +
git diff review + runnable app.

---

## 8. Business questions requiring owner approval

These are decisions for the business, not things I should invent:

**Organisation & legal**
1. Company legal setup and operating country(ies)? (Dubai data suggests UAE; sample leads suggest India. This drives compliance: UAE RERA property-sales rules, DIFC Data Protection Law, India business rules, GDPR reach, VAT/tax treatment.)
2. Is Lyka Realty a single company with departments, or multiple entities sharing the ERP?
3. Which regulator/legal frameworks must the audit log and approvals satisfy?

**Data**
4. Confirmed: keep the 6,514 Dubai rows and 9 leads as-is (prices, `bathrooms=1`, "Size: … sqm" view field, leading-space locations)? Or allow a clean-up migration?
5. Source and license of the Dubai dataset; are prices "asking", "last sold", or "estimate"? (AI/reporting must not present them as factual sale prices.)
6. Currency and tax treatment for invoice/commission figures (VAT rates, registration number, whether prices are tax-inclusive).

**Access & roles**
7. Who can self-register vs who is created by an admin? Are there external client accounts today?
8. Which department(s) may see the full lead book vs only their own assignments?
9. Confirm the role matrix in §4 (especially: can Marketing create leads; can HR view salaries; which roles may edit property status).

**Sales & finance**
10. Commission structure (fixed %, tiered, deal-type rules) and which role approves payouts.
11. Invoice numbering scheme, payment schedule defaults, and what is shown on a client statement.
12. Site-visit booking: internal-only or can clients book via the portal?

**Operations**
13. Who may authorise a property status change (Available → Sold/Rented) and what evidence is required?
14. Escalation path and SLA for maintenance/work orders.

**AI**
15. May AI agents schedule follow-ups or send communications automatically, or only **propose** (draft) them for a human to confirm?
16. Which business policies may the AI knowledge base contain, and who approves the content?

**Technical**
17. Keep SQLite as the database through Phase 3 (recommended), or move to a server DB now?
18. Any requirement for user-level email OTP / SSO, or is username+password acceptable for Phases 2–3?

Respond to these (even as "you decide" delegations with a note of who decides), and Phase 2 can begin.