"""
services/offline_extract.py
FR-02 fallback — deterministic, rule-based extraction from an enquiry.

Used when no AI credential is configured or every live provider failed. It
never invents information: every value it returns is directly evidenced by a
pattern in the customer's own text, otherwise the value stays ``None``.

The result has exactly the same shape as ``lead_schema.validate_extraction``,
so the rest of the system cannot tell (or care) which provider produced it —
except that ``ai_extract`` marks it ``degraded=True`` so the UI can tell the
agent this was NOT live AI analysis.
"""

from __future__ import annotations

import re

from services.lead_schema import empty_fields

# Communities actually present in the CRM's Dubai dataset (used for matching).
COMMUNITIES = (
    "Dubai Marina", "Downtown Dubai", "Business Bay", "Palm Jumeirah",
    "Jumeirah Village Circle", "Jumeirah Village Triangle",
    "Jumeirah Beach Residence", "Jumeirah Lake Towers", "Dubai Creek Harbour",
    "Mohammed Bin Rashid City", "Dubai Sports City", "Dubai Harbour",
    "Bur Dubai", "Al Barsha", "Umm Suqeim", "Sheikh Zayed Road",
    "Dubai Silicon Oasis", "DAMAC Hills", "Al Furjan", "Dubai South",
    "Discovery Gardens", "International City", "Dubai Investments Park",
    "The Greens", "The Springs", "The Meadows", "Town Square", "Tilal Al Ghaf",
    "Emaar South", "Liwan", "Mirdif", "Arjan", "Deira", "DIFC", "Jumeirah",
)

AMENITY_KEYWORDS = (
    (r"swim(?:ming)?\s*pool|\bpool\b", "Swimming pool"),
    (r"\bgym\b|fitness (?:centre|center)", "Gym"),
    (r"\bmetro\b|subway|metro station", "Nearby metro"),
    (r"parking|garage", "Parking"),
    (r"balcony|terrace", "Balcony"),
    (r"sea\s*view|beach\s*(?:view|front|facing)|ocean\s*view|marina\s*view",
     "Sea view"),
    (r"\bgarden\b|landscaped", "Garden"),
    (r"maids?\s*room|helper'?s?\s*room", "Maid's room"),
    (r"furnish(?:ed)?|fully furnished", "Furnished"),
    (r"security|cctv|24/?7 security", "24/7 security"),
    (r"elevator|lift", "Elevator"),
    (r"smart\s*home|home automation", "Smart home"),
    (r"private\s*pool", "Private pool"),
)

MONEY = r"(\d+(?:[.,]\d+)*)\s*(k|mn|m|million|lakh|lac|bn|billion)?"
CURRENCY_WORDS = ("AED", "USD", "INR", "EUR", "GBP", "DH", "DIRHAMS", "RUPEES", "RS")

_SUF = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
        "lakh": 1e5, "lac": 1e5, "bn": 1e9, "billion": 1e9}


def _money(match):
    if not match:
        return None, None
    try:
        value = float(match.group(1).replace(",", ""))
    except (TypeError, ValueError):
        return None, None
    suffix = (match.group(2) or "").lower()
    if suffix:
        value *= _SUF[suffix]
    if value <= 0 or value > 1e12:
        return None, None
    return int(value), None


def _find_currency(text):
    upper = text.upper()
    for word, code in (("AED", "AED"), ("DIRHAM", "AED"), ("DH", "AED"),
                       ("USD", "USD"), ("$", "USD"),
                       ("INR", "INR"), ("RUPEE", "INR"), ("₹", "INR"), ("RS.", "INR"),
                       ("EUR", "EUR"), ("GBP", "GBP")):
        if word in upper:
            return code
    return None


def _budgets(text):
    """Return (budget_min, budget_max) — only when explicitly stated."""
    lo = hi = None

    between = re.search(
        rf"between\s+{MONEY}\s*(?:and|to|-)\s*{MONEY}", text, re.I)
    if between:
        first, second = _money(between), None
        # second group pair is groups 3,4
        try:
            second_val = float(between.group(3).replace(",", ""))
            suffix = (between.group(4) or "").lower()
            if suffix:
                second_val *= _SUF[suffix]
            lo = first[0]
            hi = int(second_val) if second_val > 0 else None
        except (TypeError, ValueError, IndexError):
            lo = hi = None

    if lo is None:
        # Negative lookahead stops "within 30 days" / "up to 3 bedrooms" from
        # being mistaken for a budget figure.
        time_or_size = r"(?!\s*(?:day|week|month|year|bed|bhk|bath|room|sq|people|car))"
        for pattern in (
            rf"(?:budget\s*(?:is|of|:)?\s*(?:around|about)?|under|below|"
            rf"up\s*to|within|maximum|max(?:imum)?|no\s*more\s*than|"
            rf"less\s*than|around|about)\s*(?:[A-Z]{{2,3}}\s*)?{MONEY}(?![\d.,]){time_or_size}",
        ):
            match = re.search(pattern, text, re.I)
            if match:
                value, _ = _money(match)
                if value:
                    hi = value
                    break

    if hi is None:
        any_money = re.search(rf"(?:[A-Z]{{2,3}}\s*|₹\s*){MONEY}", text)
        if any_money and re.search(r"[A-Z]{2,3}|₹", any_money.group(0)):
            value, _ = _money(any_money)
            if value:
                hi = value

    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _timeline(text):
    lowered = text.lower()
    if re.search(r"\basap\b|immediately|right away|urgent|this week|next week", lowered):
        match = re.search(r"(?:this|next)\s+week", lowered)
        return (7 if match else 0)
    match = re.search(
        r"(?:within|in|within\s+the\s+next|next)\s+(\d+)\s*(day|days|week|weeks|month|months|year|years)",
        lowered)
    if match:
        value = int(match.group(1))
        factor = {"day": 1, "days": 1, "week": 7, "weeks": 7,
                  "month": 30, "months": 30, "year": 365, "years": 365}[match.group(2)]
        return value * factor
    if re.search(r"flexible|no\s*rush|not\s*sure|eventually|someday", lowered):
        return None
    if re.search(r"next\s+year", lowered):
        return 365
    if re.search(r"end\s+of\s+the\s+year", lowered):
        return 90
    if re.search(r"\b(?:6|six)\s*months?\b", lowered):
        return 180
    if re.search(r"\b(?:3|three)\s*months?\b", lowered):
        return 90
    if re.search(r"\b(?:1|one|a)\s*month\b", lowered):
        return 30
    return None


def _location(text):
    for community in COMMUNITIES:
        if community.lower() in text.lower():
            return community
    if re.search(r"\bdubai\b", text, re.I):
        return "Dubai"
    return None


def _name(text):
    patterns = [
        r"(?:my\s+name\s+is|my\s+name\s*:|i\s+am|i'm|im|this\s+is|call\s+me|"
        r"name\s*:)\s+([A-Za-z][A-Za-z'-]+(?:\s+[A-Za-z][A-Za-z'-]+){0,3})",
    ]
    stopwords = {
        "looking", "interested", "want", "wants", "need", "needs", "searching",
        "a", "the", "to", "for", "buying", "renting", "moving", "hoping",
        "trying", "here", "that", "this",
    }
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        candidate = match.group(1).strip()
        # Only a name the customer wrote capitalised (or that starts the
        # sentence) is taken — anything else stays unknown.
        if not candidate[:1].isupper():
            continue
        if candidate.split()[0].lower() in stopwords:
            continue
        return candidate[:120]
    return None


def _lead_type_and_purpose(text):
    lowered = text.lower()
    rent_words = re.search(
        r"\brent(?:ing|al)?\b|\blease\b|\btenant\b|\brented\b", lowered)
    buy_words = re.search(
        r"\bbuy(?:ing)?\b|\bpurchase\b|\bbuyer\b|\binvest(?:or|ing)?\b", lowered)
    sell_words = re.search(
        r"\bsell(?:ing)?\b|\blist(?:ing)?\b|\bseller\b|\bmy property\b", lowered)

    if rent_words and not buy_words:
        return "renter", "rent"
    if sell_words and not rent_words and not (buy_words and "invest" not in lowered):
        return "seller", "sell"
    if buy_words:
        return "buyer", "buy"
    return "enquiry", None


def extract_offline(text):
    """Deterministic extraction. Returns a validated-shaped fields dict."""
    fields = empty_fields()
    if not text:
        return fields

    fields["customer_name"] = _name(text)

    email = re.search(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}", text)
    if email:
        fields["email"] = email.group(0)[:120]

    phone = re.search(r"(?<!\w)(\+?\d[\d\s\-()]{7,}\d)(?!\w)", text)
    if phone:
        candidate = phone.group(1).strip()
        digits = re.sub(r"\D", "", candidate)
        # A real phone number: an explicit +, or at least 10 digits.
        if len(digits) >= 10 or candidate.startswith("+"):
            fields["phone"] = candidate[:40]

    lead_type, purpose = _lead_type_and_purpose(text)
    fields["lead_type"] = lead_type
    fields["purpose"] = purpose

    beds = re.search(r"(\d+)\s*(?:\+)?\s*(?:bed(?:room)?s?|bhk)", text, re.I)
    if beds:
        value = int(beds.group(1))
        if 0 <= value <= 50:
            fields["bedrooms"] = value

    baths = re.search(r"(\d+)\s*(?:\+)?\s*bath(?:room)?s?", text, re.I)
    if baths:
        value = int(baths.group(1))
        if 0 <= value <= 50:
            fields["bathrooms"] = value

    lo, hi = _budgets(text)
    fields["budget_min"] = lo
    fields["budget_max"] = hi
    fields["currency"] = _find_currency(text)

    fields["preferred_location"] = _location(text)

    # property type
    for keyword in ("apartment", "flat", "villa", "townhouse", "studio",
                    "penthouse", "office", "land", "compound"):
        if re.search(rf"\b{keyword}(?:s)?\b", text, re.I):
            fields["property_type"] = keyword.capitalize() if keyword != "flat" else "Apartment"
            break

    amenities = []
    for pattern, label in AMENITY_KEYWORDS:
        if re.search(pattern, text, re.I) and label not in amenities:
            amenities.append(label)
    fields["amenities"] = amenities

    days = _timeline(text)
    if days is not None:
        fields["timeline_days"] = days
        fields["timeline_label"] = (
            "immediate" if days == 0 else
            f"within {days // 30} month{'s' if days // 30 != 1 else ''}"
            if days >= 30 and days % 30 == 0 else
            f"within {days} day{'s' if days != 1 else ''}"
        )

    return fields
