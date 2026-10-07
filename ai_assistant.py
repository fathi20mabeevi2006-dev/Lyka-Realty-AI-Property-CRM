"""
ai_assistant.py
A simple rule-based AI assistant for the Property CRM.

It reads REAL data from the SQLite database and answers natural
language questions. No external AI API or internet required -
perfect for beginners to understand and extend later.
"""

import re
from database import get_all_properties, get_all_leads, get_dashboard_stats


# ---------- helpers ----------

def _matches_location(prop_location: str, city: str) -> bool:
    """Case-insensitive location match (handles 'Dubai', 'dubai', 'dubai marina', etc.)."""
    if not city:
        return True
    return city.lower() in (prop_location or "").lower()


def _matches_yes(value, user_says_yes: bool) -> bool:
    if not user_says_yes:
        return True
    return str(value).strip().lower() in ("yes", "y", "true")


# Known "Property View" values the assistant can search for.
VIEW_TYPES = [
    "sea", "city", "beach", "garden", "lake", "pool",
    "canal", "market", "street", "forest", "hill",
]


def _parse_floor(q_lower: str):
    """
    Extract a floor filter from the question.
    Returns: int (exact floor), "high" (>= 10), or None.
    """
    m = re.search(r"floor(?:\s*number)?\s*#?\s*(\d+)", q_lower)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+floor", q_lower)
    if m:
        return int(m.group(1))
    if "ground floor" in q_lower:
        return 0
    if "high floor" in q_lower:
        return "high"
    return None


def _parse_view(q_lower: str):
    """Extract a 'Property View' filter (e.g. 'sea view' -> 'sea')."""
    for view in VIEW_TYPES:
        if f"{view} view" in q_lower:
            return view
    return None


def _filter_properties(props, beds=None, city=None, wants_pool=False,
                       wants_metro=False, view=None, floor=None,
                       is_available=False, is_sold=False, is_rented=False):
    """Apply every active filter to a list of property dicts."""
    result = []
    for p in props:
        if beds is not None and int(p["bedrooms"]) != beds:
            continue
        if city and not _matches_location(p["location"], city):
            continue
        if wants_pool and not _matches_yes(p["has_swimming_pool"], True):
            continue
        if wants_metro and not _matches_yes(p["nearby_metro"], True):
            continue
        if view and view not in (p.get("property_view") or "").lower():
            continue
        if floor is not None:
            number = p.get("floor_number")
            if floor == "high":
                if number is None or int(number) < 10:
                    continue
            elif number is None or int(number) != floor:
                continue
        if is_available and p["status"].lower() != "available":
            continue
        if is_sold and p["status"].lower() != "sold":
            continue
        if is_rented and p["status"].lower() != "rented":
            continue
        result.append(p)
    return result


def _describe_filters(beds=None, city=None, wants_pool=False, wants_metro=False,
                      view=None, floor=None, status_word=None) -> str:
    """Human-readable summary of the active filters (for count answers)."""
    parts = []
    if beds is not None:
        parts.append(f"{beds}-bedroom")
    if city:
        parts.append(f"in {city.title()}")
    if wants_pool:
        parts.append("with a swimming pool")
    if wants_metro:
        parts.append("near a metro")
    if view:
        parts.append(f"with a {view} view")
    if floor == "high":
        parts.append("on a high floor (10+)")
    elif floor is not None:
        parts.append(f"on floor {floor}")
    if status_word:
        parts.append(f"that are {status_word}")
    return " ".join(parts)


def _format_price(price) -> str:
    try:
        return f"₹{float(price):,.0f}"
    except (TypeError, ValueError):
        return str(price)


def _format_property(p: dict, index: int) -> str:
    return (
        f"{index}. **{p['name']}** — {_format_price(p['price'])}\n"
        f"   Location: {p['location']} | Beds: {p['bedrooms']} | "
        f"Baths: {p['bathrooms']} | Floor: {p.get('floor_number') or 'N/A'}\n"
        f"   View: {p.get('property_view') or 'N/A'} | Pool: {p['has_swimming_pool']} | "
        f"Metro: {p['nearby_metro']} | Status: {p['status']}"
    )


def _keyword_list() -> str:
    return (
        "**Try asking things like:**\n"
        "- `Show me properties with a swimming pool.`\n"
        "- `Show me properties near a metro station.`\n"
        "- `Show me sea-view properties.`\n"
        "- `Show me properties on the 15th floor.`\n"
        "- `Show me 2-bedroom properties in Dubai with swimming pool`\n"
        "- `How many properties are sold?`\n"
        "- `Show available properties in Chennai`\n"
        "- `How many properties have a swimming pool?`\n"
        "- `How many leads do I have?`\n"
        "- `List all properties`\n"
        "- `Give me stats`"
    )


# ---------- main entry ----------

def answer_question(question: str) -> str:
    """Parse the user's question and return a helpful answer from CRM data."""
    q = (question or "").strip()
    if not q:
        return "Please type a question so I can help you! 🙂\n\n" + _keyword_list()

    q_lower = q.lower()

    # Normalize punctuation so hyphenated words still parse correctly
    # (e.g. "sea-view" -> "sea view", "15th-floor" -> "15th floor")
    q_lower = re.sub(r"[-‐-―_/.,;:()!?]+", " ", q_lower)
    q_lower = re.sub(r"\s+", " ", q_lower).strip()

    # --- greetings / help ---
    if q_lower in ("hi", "hello", "hey", "hola", "yo"):
        return (
            "Hello! I'm your Property CRM assistant. 🏠\n"
            "I can search your properties, check leads, and give dashboard stats.\n\n"
            + _keyword_list()
        )
    if q_lower in ("help", "what can you do", "commands", "?"):
        return _keyword_list()

    # --- extract a bedroom number if mentioned (e.g. "2-bedroom", "2 bedroom", "2BHK") ---
    bedroom_match = re.search(r"(\d+)\s*-?\s*(?:bed(?:room)?s?|bhk)", q_lower)
    beds = int(bedroom_match.group(1)) if bedroom_match else None

    # --- extract a location/city from a small known list + the text after common keywords ---
    cities = [
        "dubai", "chennai", "mumbai", "delhi", "bangalore", "bengaluru",
        "hyderabad", "pune", "kolkata", "ahmedabad", "jaipur", "kochi",
        "goa", "london", "new york", "singapore", "toronto", "sydney",
        "chandigarh", "lucknow", "surat", "indore", "nagpur",
    ]
    city = next((c for c in cities if c in q_lower), None)
    if not city:
        # fallback: text after "in" that isn't a common filler word
        m = re.search(r"\bin\s+([a-z][a-z\s]{1,30}?)(?:\s+(?:with|and|that|which|under|below|costing|budget|less|available|for)|$|[.,?])", q_lower)
        if m:
            candidate = m.group(1).strip()
            if candidate and candidate not in ("the", "a", "an", "my", "your", "some", "all", "any"):
                city = candidate

    wants_pool = bool(re.search(r"pool|swimming|swim", q_lower))
    wants_metro = bool(re.search(r"metro|subway|underground|transit", q_lower))

    # --- "Property View" filter (e.g. "sea view properties") ---
    view_wanted = _parse_view(q_lower)
    if view_wanted == "pool" and "pool view" in q_lower:
        # "pool view" is a view type, not necessarily an own-pool requirement
        wants_pool = False

    # --- Floor filter (e.g. "floor 5", "3rd floor", "ground floor", "high floor") ---
    floor_wanted = _parse_floor(q_lower)

    # --- "show/list/find" questions should return listings, not counts ---
    search_intent = bool(re.search(r"\b(show|list|find|display|search)\b", q_lower))

    # --- count questions ---
    wants_count = bool(re.search(r"how many|count|number of", q_lower))

    # --- status questions ---
    is_sold = bool(re.search(r"\bsold\b", q_lower))
    is_rented = bool(re.search(r"\brented\b|rent\b", q_lower))
    is_available = bool(re.search(r"available", q_lower))

    # --- stats / dashboard ---
    if re.search(r"stats|statistic|dashboard|overview|summary", q_lower) and not wants_count:
        s = get_dashboard_stats()
        return (
            "📊 **CRM Dashboard Snapshot**\n\n"
            f"- Total Properties: **{s['total_properties']}**\n"
            f"- Available: **{s['available']}**\n"
            f"- Sold: **{s['sold']}**\n"
            f"- Rented: **{s['rented']}**\n"
            f"- Total Leads: **{s['total_leads']}**"
        )

    if (wants_count or is_sold or is_rented) and not (search_intent and not wants_count):
        stats = get_dashboard_stats()

        # Lead/client questions always answer with lead counts
        if re.search(r"lead|client", q_lower):
            return f"👤 You currently have **{stats['total_leads']} leads/clients** in your CRM."

        extra_filters = (
            beds is not None or city or wants_pool or wants_metro
            or view_wanted or floor_wanted is not None
        )

        # Simple status / count questions keep the classic answers
        if not extra_filters:
            if re.search(r"sold", q_lower):
                return f"✅ There are **{stats['sold']} properties** currently marked as *Sold* in your CRM."
            if re.search(r"rented", q_lower):
                return f"🏠 There are **{stats['rented']} properties** currently marked as *Rented* in your CRM."
            if re.search(r"available", q_lower):
                return f"🟢 There are **{stats['available']} properties** currently marked as *Available* in your CRM."
            return (
                "📊 **Quick counts:**\n\n"
                f"- Total Properties: **{stats['total_properties']}**\n"
                f"- Available: **{stats['available']}** | Sold: **{stats['sold']}** | "
                f"Rented: **{stats['rented']}**\n"
                f"- Total Leads: **{stats['total_leads']}**"
            )

        # Count with combined filters (pool, metro, view, floor, city, beds, status)
        matched = _filter_properties(
            get_all_properties(), beds=beds, city=city,
            wants_pool=wants_pool, wants_metro=wants_metro,
            view=view_wanted, floor=floor_wanted,
            is_available=is_available, is_sold=is_sold, is_rented=is_rented,
        )
        status_word = (
            "available" if is_available else
            ("sold" if is_sold else ("rented" if is_rented else None))
        )
        description = _describe_filters(
            beds=beds, city=city, wants_pool=wants_pool, wants_metro=wants_metro,
            view=view_wanted, floor=floor_wanted, status_word=status_word,
        ) or "your criteria"
        count = len(matched)
        return (
            f"🔎 There {'is' if count == 1 else 'are'} **{count} "
            f"propert{'y' if count == 1 else 'ies'}** matching **{description}**."
        )

    # --- search properties ---
    if re.search(r"propert|apartment|villa|home|flat|show me|find|list|search|looking", q_lower):
        result = _filter_properties(
            get_all_properties(), beds=beds, city=city,
            wants_pool=wants_pool, wants_metro=wants_metro,
            view=view_wanted, floor=floor_wanted,
            is_available=is_available, is_sold=is_sold, is_rented=is_rented,
        )

        if not result:
            hints = []
            if beds is not None:
                hints.append(f"{beds}-bedroom")
            if city:
                hints.append(f"in {city.title()}")
            if wants_pool:
                hints.append("with swimming pool")
            if wants_metro:
                hints.append("near metro")
            if view_wanted:
                hints.append(f"with {view_wanted} view")
            if floor_wanted == "high":
                hints.append("on a high floor (10+)")
            elif floor_wanted is not None:
                hints.append(f"on floor {floor_wanted}")
            if is_available:
                hints.append("available")
            detail = " ".join(hints) if hints else "your criteria"
            return (
                f"😕 No properties found matching **{detail}**.\n\n"
                f"💡 Try widening your search, or use the **Properties** page to add new listings.\n\n"
                + _keyword_list()
            )

        # cap output so the chat stays readable
        shown = result[:10]
        header = f"🏠 Found **{len(result)}** matching propert{'y' if len(result) == 1 else 'ies'}"
        if city:
            header += f" in **{city.title()}**"
        if beds is not None:
            header += f" with **{beds}** bedroom{'s' if beds != 1 else ''}"
        if wants_pool:
            header += " + 🏊 swimming pool"
        if wants_metro:
            header += " + 🚇 nearby metro"
        if view_wanted:
            header += f" + 🖼 {view_wanted} view"
        if floor_wanted == "high":
            header += " + 🏗 high floor"
        elif floor_wanted is not None:
            header += f" + 🏗 floor {floor_wanted}"
        if is_available:
            header += " (Available)"
        header += ":\n"

        body = "\n\n".join(_format_property(p, i + 1) for i, p in enumerate(shown))
        more = f"\n\n…and **{len(result) - len(shown)}** more not shown."
        return header + "\n\n" + body + more

    # --- leads ---
    if re.search(r"lead|client|customer", q_lower):
        leads = get_all_leads()
        return f"👤 You currently have **{len(leads)} leads/clients** stored in the CRM.\n\n" + _keyword_list()

    # --- fallback ---
    return (
        "🤖 I'm not sure how to answer that yet, but here are some things I can do:\n\n"
        + _keyword_list()
    )
