"""
brd.py
Phase 4 — Business Requirements Document (BRD) generator.

The single source of truth for the BRD: ONE function builds a plain Python
dictionary ("document model") that is rendered BOTH by the web preview
(templates/brd.html) and by the PDF exporter (services/pdf_exporter.py).
This keeps the preview and the downloaded PDF always in sync.

Safety rules honoured here:
  - READ-ONLY: only reads crm.db through the existing database helpers.
  - No files are written, no tables/rows are created, modified or deleted.
  - Missing information is reported honestly ("not documented") and is
    NEVER invented.
  - Live counts are included only if they can be verified (they are straight
    COUNT(*) queries on real tables). The portfolio value is included only
    because its calculation is explained in full (sum of the stored price of
    the priced properties; unpriced properties are excluded).
"""

from datetime import datetime

from config import CURRENCY
from database import (
    get_dashboard_stats,
    get_all_business_entries,
    get_all_requirements,
    get_gap_analysis,
    PRIORITY_RANK,
)

DOC_TITLE = "Business Requirements Document"
COMPANY_NAME = "Lyka Realty"

_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _fmt_number(num):
    """Thousands-separated integer, safe for empty/missing values."""
    try:
        return f"{int(round(float(num or 0))):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_money(num):
    """Currency label + thousands-separated value (e.g. 'AED 123,456,789')."""
    return f"{CURRENCY} {_fmt_number(num)}"


def _entry_row(raw):
    """Normalize a business_analysis row into a small, template-friendly dict."""
    return {
        "category": (raw.get("category") or "").strip() or "Other",
        "title": (raw.get("title") or "").strip(),
        "details": (raw.get("details") or "").strip(),
        "source_type": (raw.get("source_type") or "").strip() or "Fact",
        "status": (raw.get("status") or "").strip() or "Draft",
    }


def _req_row(raw, has_gap):
    """Normalize a requirements row for the BRD."""
    return {
        "title": (raw.get("title") or "").strip(),
        "req_type": (raw.get("req_type") or "").strip() or "Functional",
        "category": (raw.get("category") or "").strip() or "Other",
        "priority": (raw.get("priority") or "").strip() or "Medium",
        "status": (raw.get("status") or "").strip() or "Draft",
        "owner": (raw.get("owner") or "").strip(),
        "description": (raw.get("description") or "").strip(),
        "problem": (raw.get("problem") or "").strip(),
        "proposed_solution": (raw.get("proposed_solution") or "").strip(),
        "acceptance_criteria": (raw.get("acceptance_criteria") or "").strip(),
        "dependencies": (raw.get("dependencies") or "").strip(),
        "risks": (raw.get("risks") or "").strip(),
        "current_state": (raw.get("current_state") or "").strip(),
        "desired_state": (raw.get("desired_state") or "").strip(),
        "gap_notes": (raw.get("gap_notes") or "").strip(),
        "has_gap": bool(has_gap),
    }


def _sort_key(req):
    """Sort requirements High -> Medium -> Low, then by title."""
    return (_PRIORITY_ORDER.get(req["priority"], 9), req["title"].lower())


def build_brd():
    """Return the BRD document model as a plain dictionary (read-only)."""
    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M")

    # ---------------------------------------------------------------- facts
    stats = get_dashboard_stats()
    priced = stats.get("priced_count") or 0
    current_state = {
        "stats_label": (
            "The figures below are verified directly from the CRM database "
            f"as of {generated_at}."
        ),
        "facts": [
            {
                "label": "Total properties",
                "value": _fmt_number(stats.get("total_properties")),
                "note": "Count of all property records in the CRM database.",
            },
            {
                "label": "Available properties",
                "value": _fmt_number(stats.get("available")),
                "note": "Count of properties with status 'Available'.",
            },
            {
                "label": "Sold properties",
                "value": _fmt_number(stats.get("sold")),
                "note": "Count of properties with status 'Sold'.",
            },
            {
                "label": "Rented properties",
                "value": _fmt_number(stats.get("rented")),
                "note": "Count of properties with status 'Rented'.",
            },
            {
                "label": "Total property leads",
                "value": _fmt_number(stats.get("total_leads")),
                "note": "Count of all lead records in the CRM database.",
            },
            {
                "label": "Portfolio value (listed prices)",
                "value": _fmt_money(stats.get("portfolio_value")),
                "note": (
                    f"Sum of the stored listed price of {_fmt_number(priced)} "
                    f"priced properties (out of {_fmt_number(stats.get('total_properties'))} "
                    "total). Properties without a stored price are excluded, "
                    "so this is a lower-bound figure — it is not the full portfolio."
                ),
            },
            {
                "label": "Average listed price",
                "value": _fmt_money(stats.get("average_price")),
                "note": (
                    f"Average of the stored listed price across the "
                    f"{_fmt_number(priced)} priced properties."
                ),
            },
        ],
    }

    # ------------------------------------------------- business analysis notes
    entries = [_entry_row(e) for e in get_all_business_entries()]

    def _by_category(category):
        return [e for e in entries if e["category"] == category]

    def _by_source(source_type):
        return [e for e in entries if e["source_type"] == source_type]

    company_profile = _by_category("Company Profile")
    objectives = _by_category("Objectives")
    facts = _by_source("Fact")
    assumptions = _by_source("Assumption")
    recommendations = _by_source("Recommendation")

    # ------------------------------------------------------------- requirements
    gap_view = get_gap_analysis()
    gap_by_id = {i["id"]: i.get("has_gap") for i in gap_view.get("items", [])}
    reqs = [_req_row(r, gap_by_id.get(r["id"], False)) for r in get_all_requirements()]

    functional = sorted(
        [r for r in reqs if r["req_type"] == "Functional"], key=_sort_key)
    non_functional = sorted(
        [r for r in reqs if r["req_type"] == "Non-Functional"], key=_sort_key)

    problems = [
        {"title": r["title"], "text": r["problem"], "priority": r["priority"],
         "status": r["status"]}
        for r in sorted(reqs, key=_sort_key) if r["problem"]
    ]
    solutions = [
        {"title": r["title"], "text": r["proposed_solution"],
         "priority": r["priority"], "status": r["status"]}
        for r in sorted(reqs, key=_sort_key) if r["proposed_solution"]
    ]

    gap_items = [
        {"title": r["title"], "priority": r["priority"], "status": r["status"]}
        for r in sorted(reqs, key=_sort_key)
        if r["has_gap"] and (r["current_state"] or r["desired_state"] or r["gap_notes"])
    ]

    # ------------------------------------------------------- missing information
    missing = []

    if not entries:
        missing.append(
            "No Business Analysis notes are documented yet. Add notes on the "
            "Business Analysis page so the BRD can describe the company, "
            "objectives, facts and assumptions."
        )
    if not company_profile:
        missing.append(
            "Company profile is not documented — add a Business Analysis note "
            "in the 'Company Profile' category."
        )
    if not objectives:
        missing.append(
            "Business objectives are not documented — add a Business Analysis "
            "note in the 'Objectives' category."
        )
    for source_type, section_label in (
        ("Fact", "documented facts"),
        ("Assumption", "assumptions"),
        ("Recommendation", "recommendations"),
    ):
        if not _by_source(source_type):
            missing.append(
                f"No {section_label} are recorded in Business Analysis."
            )

    if not reqs:
        missing.append(
            "No requirements are documented yet. Add requirements on the "
            "Requirements page so the BRD can list problems, solutions and "
            "acceptance criteria."
        )
    else:
        without_problem = [r for r in reqs if not r["problem"]]
        without_solution = [r for r in reqs if not r["proposed_solution"]]
        without_acceptance = [r for r in reqs if not r["acceptance_criteria"]]
        without_gap_states = [
            r for r in reqs if not r["current_state"] or not r["desired_state"]]

        for items, field in (
            (without_problem, "a documented business problem"),
            (without_solution, "a proposed solution"),
            (without_acceptance, "acceptance criteria"),
        ):
            if items:
                names = "', '".join(r["title"] for r in items)
                missing.append(
                    f"{len(items)} requirement(s) have no {field}: "
                    f"'{names}'."
                )
        if without_gap_states:
            names = "', '".join(r["title"] for r in without_gap_states)
            missing.append(
                f"{len(without_gap_states)} requirement(s) have no gap "
                f"analysis (current/desired state): '{names}'."
            )

    return {
        "meta": {
            "title": DOC_TITLE,
            "company": COMPANY_NAME,
            "generated_at": generated_at,
            "generated_by": "local (automatic)",
            "currency": CURRENCY,
            "source_note": (
                "Prepared automatically from the Business Analysis and "
                "Requirements modules of the AI Property CRM. Where "
                "information is missing it is clearly marked 'not "
                "documented' — nothing is invented."
            ),
        },
        "current_state": current_state,
        "company_profile": company_profile,
        "objectives": objectives,
        "fact_base": facts,
        "assumptions": assumptions,
        "recommendations": recommendations,
        "problems": problems,
        "solutions": solutions,
        "functional": functional,
        "non_functional": non_functional,
        "gap_summary": {
            "total": gap_view.get("total", 0),
            "gap_count": gap_view.get("gap_count", 0),
            "gaps": gap_items,
        },
        "missing": missing,
        "totals": {
            "business_notes": len(entries),
            "requirements": len(reqs),
        },
    }


# Convenience getter so templates and exporters can ask for the health check.
def brd_summary():
    """Small counts used by the BRD preview page header cards."""
    doc = build_brd()
    return {
        "business_notes": doc["totals"]["business_notes"],
        "requirements": doc["totals"]["requirements"],
        "gaps": doc["gap_summary"]["gap_count"],
        "documented_facts": len(doc["fact_base"])
        + len(doc["company_profile"]) + len(doc["current_state"]["items"]),
    }


if __name__ == "__main__":
    import json

    model = build_brd()
    print(json.dumps({
        "meta": model["meta"],
        "current_state": model["current_state"]["items"],
        "counts": {
            "profile": len(model["company_profile"]),
            "objectives": len(model["objectives"]),
            "facts": len(model["fact_base"]),
            "assumptions": len(model["assumptions"]),
            "recommendations": len(model["recommendations"]),
            "problems": len(model["problems"]),
            "solutions": len(model["solutions"]),
            "functional": len(model["functional"]),
            "non_functional": len(model["non_functional"]),
            "missing": len(model["missing"]),
        },
    }, indent=2, ensure_ascii=False))