# Test Report — Lyka Realty AI Property CRM

**Date:** 2026-10-10
**Command:** `python -m unittest discover -s tests`
**Result:** **110 tests, OK** (0 failures, 0 errors) — 64 pre-existing + 46 new.

All tests run against a **disposable copy** of `crm.db` (`tests/helpers.py` copies the
real database to a temp file, repoints `database.DB_PATH`, migrates the copy). The real
database is never modified by the test suite.

---

## 1. New test modules

| Module | Tests | Covers |
|---|---|---|
| `tests/test_qualification.py` | 7 | FR-04 scoring: weights, cap, priority boundaries (69/70, 39/40), exclusive timeline bands, garbage input safety |
| `tests/test_matching.py` | 10 | FR-06: purpose/availability hard filters, wrong-location exclusion, unknown-criteria handling, budget mismatch, weight sanity, persistence + history |
| `tests/test_ai_extraction.py` | 13 | FR-02/03: enquiry bounds, schema validation, missing-field/questions, offline determinism, no key leakage, provider fallback |
| `tests/test_lead_analysis.py` | 16 | FR-01/07/08/09/10: analyse screens + RBAC, save flow, lead detail, notes, status history, client isolation, recommendations page/API, dashboard KPIs, AI status API |

## 2. PRD §L scenario coverage

| # | Scenario | Test |
|---|---|---|
| 1 | Buyer with budget & requirements | `test_matching.MatchingIntegrationTests.test_sale_lead_gets_sale_listings` |
| 2 | Rental enquiry | `test_matching.MatchingIntegrationTests.test_recommendations_persist_and_history_grows`; `test_matching.MatchingUnitTests.test_purpose_is_a_hard_filter` |
| 3 | Multiple amenities | `test_matching.test_unknown_criteria_excluded_not_penalised`; `test_qualification` breakdown |
| 4 | Specified purchase timeline | `test_qualification.QualificationTests.test_timeline_bands_are_exclusive` |
| 5 | Successful recommendations | `test_lead_analysis.RecommendationsTests.test_generate_and_view_matches` |
| 6 | Missing budget | `test_ai_extraction.ValidationTests.test_missing_fields_and_questions_are_derived` |
| 7 | Missing/ambiguous location | `test_matching.MatchingUnitTests.test_wrong_location_is_not_a_match`; `test_empty_criteria_is_honest_no_match` |
| 8 | Conflicting requirements | `test_ai_extraction.ValidationTests.test_budget_min_greater_than_max_is_rejected` |
| 9 | OpenAI failure/timeout | `test_ai_extraction.ExtractionTests.test_unknown_provider_falls_back_to_a_real_provider` (keys forced empty) |
| 10 | Invalid AI response | `test_ai_extraction.ValidationTests.test_validator_never_raises_on_junk`, `test_validator_ignores_unknown_choice` |

Additional edge cases: empty/oversized enquiry (`test_empty_enquiry_rejected`,
`test_overlong_enquiry_rejected`), duplicate submission (disabled in template + 302→GET
redirect), unavailable property (`test_unavailable_listings_are_never_returned`),
unauthorised operations (`test_finance_role_cannot_analyse`,
`test_client_cannot_view_another_clients_lead`, `test_api_requires_csrf`).

## 3. Manual / CLI verification

| Check | Result |
|---|---|
| Live Groq extraction | OK — provider `groq`, model `openai/gpt-oss-20b`, ~2.7 s |
| OpenAI live | BLOCKED — no `OPENAI_API_KEY` |
| Migration on real DB | OK — backup `backups/crm_backup_20261010_140946.db`; 6 514 props / 9 leads; 0 NULL priorities |
| Demo seed | OK — 12 `is_demo=1` listings added; existing rows unchanged |
| Match smoke | Sale → 100/78/63; Rent → 100/38; impossible location → honest no-match |
| Route smoke | all new GET/POST routes return expected 200/302; APIs return JSON |

## 4. Regression gate

`python -m unittest discover -s tests` must remain green before any further change.
Baseline (pre-change) was 64 OK; current is 110 OK.
