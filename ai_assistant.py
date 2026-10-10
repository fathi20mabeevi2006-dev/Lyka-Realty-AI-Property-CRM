"""
ai_assistant.py
Offline, rule-based assistant that answers questions from the LIVE CRM database.

It needs no internet and no API key. It is used:
  * directly when Groq is not configured, and
  * as the fallback if the external AI call fails.

Every answer is built from real SQLite rows — it never invents data.
The visible currency symbol comes from config.CURRENCY (prices are never changed).
"""

from datetime import datetime

from database import get_all_properties, get_all_leads, get_dashboard_stats
from config import CURRENCY

MAX_LIST = 10  # how many properties to list in a single answer


def _money(value):
    try:
        return f"{CURRENCY} {float(value):,.0f}"
    except (TypeError, ValueError):
        return f"{CURRENCY} 0"


def _lower(value):
    return str(value or "").lower()


def _property_lines(properties):
    lines = []
    for p in properties[:MAX_LIST]:
        lines.append(
            f"- {p['name']} | {_money(p['price'])} | "
            f"{p['bedrooms']} bed | {p['location']} | {p['status']}"
        )
    return "\n".join(lines)


def _yes(prop_value):
    return str(prop_value or "").strip().lower() == "yes"


def _match_location(properties, name):
    """Properties whose location contains the given place name."""
    needle = name.lower()
    return [p for p in properties if needle in _lower(p["location"])]


# ---------------------------------------------------------------- answer engine

def answer_question(question):
    """Return a database-grounded answer string for the given question."""
    question = (question or "").lower().strip()
    properties = get_all_properties()
    leads = get_all_leads()
    stats = get_dashboard_stats()

    # --- top-line stats ---
    if any(word in question for word in ("dashboard", "stats", "statistics", "overview", "summary")):
        return (
            "CRM Dashboard Snapshot\n\n"
            f"Properties: {stats['total_properties']} total\n"
            f"  Available: {stats['available']}\n"
            f"  Sold: {stats['sold']}\n"
            f"  Rented: {stats['rented']}\n"
            f"Leads: {stats['total_leads']}\n"
            f"Portfolio value: {_money(stats['portfolio_value'])}\n"
            f"Average price: {_money(stats['average_price'])}"
        )

    # --- leads ---
    if "how many lead" in question or "total lead" in question or "number of lead" in question:
        return f"You currently have {len(leads)} leads."

    if "follow" in question and ("due" in question or "overdue" in question):
        today = datetime.now().strftime("%Y-%m-%d")
        due = [
            l for l in leads
            if l.get("next_follow_up") and str(l["next_follow_up"]) <= today
        ]
        if not due:
            return "No follow-ups are due or overdue right now."
        names = ", ".join(l["client_name"] for l in due[:MAX_LIST])
        return (
            f"{len(due)} lead(s) have a follow-up due or overdue: {names}."
        )

    # --- status counts ---
    if "available" in question and "propert" in question or question in ("available properties", "available"):
        return f"There are {stats['available']} available properties."
    if "sold" in question and "propert" in question:
        return f"There are {stats['sold']} sold properties."
    if "rented" in question and "propert" in question:
        return f"There are {stats['rented']} rented properties."

    # --- amenity counts ---
    if "pool" in question and "how many" in question:
        n = sum(1 for p in properties if _yes(p.get("has_swimming_pool")))
        return f"{n} properties have a swimming pool."
    if ("metro" in question or "near metro" in question) and "how many" in question:
        n = sum(1 for p in properties if _yes(p.get("nearby_metro")))
        return f"{n} properties are near a metro station."

    # --- cheapest / most expensive ---
    if properties:
        if "cheapest" in question or "least expensive" in question:
            p = min(properties, key=lambda x: float(x.get("price") or 0))
            return (
                f"Cheapest property:\n\n{p['name']}\n"
                f"{p['location']}\n{_money(p['price'])}"
            )
        if "expensive" in question or "priciest" in question:
            p = max(properties, key=lambda x: float(x.get("price") or 0))
            return (
                f"Most expensive property:\n\n{p['name']}\n"
                f"{p['location']}\n{_money(p['price'])}"
            )

    # --- pool / metro listings ---
    if "pool" in question and "how many" not in question:
        results = [p for p in properties if _yes(p.get("has_swimming_pool"))]
        return _listing_reply("with a swimming pool", results)

    if ("metro" in question or "metro station" in question) and "how many" not in question:
        results = [p for p in properties if _yes(p.get("nearby_metro"))]
        return _listing_reply("near a metro station", results)

    # --- budget cap, e.g. "under 10000000" ---
    budget = _extract_budget(question)
    if budget is not None:
        results = [p for p in properties if float(p.get("price") or 0) <= budget]
        return _listing_reply(f"under {_money(budget)}", results)

    # --- bedroom search ---
    beds = _extract_bedrooms(question)
    if beds is not None:
        results = [p for p in properties if int(p.get("bedrooms") or 0) == beds]
        return _listing_reply(f"with {beds} bedroom(s)", results)

    # --- location search (against the real locations stored in the DB) ---
    for place in _known_locations(properties):
        if place.lower() in question:
            results = _match_location(properties, place)
            return _listing_reply(f"in {place.title()}", results)

    # --- fallback: grounded snapshot + help ---
    return _help_text(stats, properties)


def _listing_reply(label, results):
    if not results:
        return f"No properties found {label}."
    header = f"Found {len(results)} properties {label}:"
    return header + "\n\n" + _property_lines(results)


def _help_text(stats, properties):
    top_locations = _top_locations(properties)
    return (
        "I can answer from your live CRM data. Try:\n"
        "- Dashboard stats\n"
        "- How many leads?\n"
        "- Available / sold / rented properties\n"
        "- Cheapest / most expensive property\n"
        "- Properties with a swimming pool / near a metro\n"
        "- 2 bedroom properties\n"
        "- Properties under 5000000\n"
        f"- Properties in {top_locations[0] if top_locations else 'Dubai'}\n\n"
        f"Current snapshot: {stats['total_properties']} properties, "
        f"{stats['available']} available, {stats['total_leads']} leads."
    )


# ---------------------------------------------------------------- helpers

def _known_locations(properties):
    """Real location strings from the DB, longest first (so 'Dubai Marina'
    wins over 'Dubai')."""
    seen = {}
    for p in properties:
        loc = str(p.get("location") or "").strip()
        if loc:
            seen[loc] = seen.get(loc, 0) + 1
    return sorted(seen, key=len, reverse=True)


def _top_locations(properties, limit=8):
    counts = {}
    for p in properties:
        loc = str(p.get("location") or "").strip()
        if loc:
            counts[loc] = counts.get(loc, 0) + 1
    return [loc for loc, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]]


def _extract_bedrooms(question):
    for bed in range(1, 11):
        if f"{bed} bedroom" in question or f"{bed} bed" in question or f"{bed}bhk" in question or f"{bed} bhk" in question:
            return bed
    return None


def _extract_budget(question):
    """Parse 'under 5000000' / 'below 5,000,000' style budgets. Returns None if absent."""
    import re

    match = re.search(r"(?:under|below|less than|up to|max(?:imum)?)\s*([\d,\.]+)", question)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


# ---------------------------------------------------- grounding for the LLM

def grounding_context(question):
    """Return a compact block of VERIFIED database facts for the AI prompt.

    Only aggregate facts and non-sensitive property details are included —
    never customer phone numbers or emails.
    """
    question = (question or "").lower().strip()
    properties = get_all_properties()
    stats = get_dashboard_stats()
    leads = get_all_leads()

    lines = [
        "VERIFIED CRM DATA (from SQLite — use only these facts, do not invent):",
        f"- Total properties: {stats['total_properties']} "
        f"(Available {stats['available']}, Sold {stats['sold']}, Rented {stats['rented']})",
        f"- Total leads: {stats['total_leads']}",
        f"- Portfolio value: {_money(stats['portfolio_value'])}",
        f"- Average property price: {_money(stats['average_price'])}",
    ]

    top_locations = _top_locations(properties)
    if top_locations:
        lines.append("- Top locations: " + ", ".join(top_locations))

    # Add matching properties if the question points at something specific.
    relevant = []
    for place in _known_locations(properties):
        if place.lower() in question:
            relevant = _match_location(properties, place)
            lines.append(f"- Matching location '{place}': {len(relevant)} properties")
            break

    beds = _extract_bedrooms(question)
    if beds is not None:
        relevant = [p for p in properties if int(p.get("bedrooms") or 0) == beds]
        lines.append(f"- Matching {beds}-bedroom properties: {len(relevant)}")

    if "pool" in question:
        n = sum(1 for p in properties if _yes(p.get("has_swimming_pool")))
        lines.append(f"- Properties with a swimming pool: {n}")
    if "metro" in question:
        n = sum(1 for p in properties if _yes(p.get("nearby_metro")))
        lines.append(f"- Properties near a metro: {n}")

    if relevant:
        lines.append("- Example matching properties:")
        for p in relevant[:MAX_LIST]:
            lines.append(
                f"    {p['name']} | {_money(p['price'])} | "
                f"{p['bedrooms']} bed | {p['location']} | {p['status']}"
            )

    return "\n".join(lines)
