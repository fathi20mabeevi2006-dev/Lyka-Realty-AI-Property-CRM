"""
services/qualification.py
FR-04 — transparent, rule-based lead qualification scoring.

The scoring table below is exactly the PRD specification:

    Budget provided ............ 20
    Preferred location ......... 20
    Property type or bedrooms .. 15
    Buying/renting intent ...... 15
    Timeline within 30 days .... 20   (exclusive)
    Timeline 31-90 days ........ 15   (exclusive)
    Timeline beyond 90 days .... 5    (exclusive)
    Timeline unknown ........... 0    (exclusive)
    Essential preferences ...... 10

    High   = 70-100
    Medium = 40-69
    Low    = 0-39

Rules honoured by score_lead():
  * only ONE timeline rule can ever award points,
  * the total is capped at 100 and floored at 0,
  * unknown information earns nothing (never invents),
  * the full breakdown and the reason for every award is returned so the
    UI can show agents exactly why a lead scored what it scored,
  * QUALIFICATION_RULES is data, not code — the weights can be changed in
    one place (or overridden per call) without touching the logic.

This module must NOT import database/app (keeps it dependency-free and
trivially testable).
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Configuration (single place to tune the weights / thresholds)
# --------------------------------------------------------------------------- #

PRIORITY_THRESHOLDS = (
    ("High", 70),
    ("Medium", 40),
    ("Low", 0),
)

MAX_SCORE = 100

# timeline bands, in days — first match wins, so only one can ever apply
TIMELINE_BANDS = (
    (30, "within 30 days", 20),
    (90, "within 31-90 days", 15),
    (None, "beyond 90 days", 5),
)

ESSENTIAL_PREFERENCE_KEYS = (
    "amenities", "bathrooms_needed", "bathrooms", "min_area", "area_sqft",
    "property_view", "floor_number", "other_preferences",
)


def _has(value) -> bool:
    """True when a value carries real information (empty string == unknown)."""
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (int, float)):
        return True
    return bool(value)


def _budget_present(data) -> bool:
    return any(_has(data.get(k)) for k in ("budget", "budget_max", "budget_min"))


def _type_or_bedrooms_present(data) -> bool:
    if _has(data.get("property_type")):
        return True
    if _has(data.get("bedrooms_needed")) or _has(data.get("bedrooms")):
        return True
    return _has(data.get("lead_type")) and str(
        data.get("lead_type") or ""
    ).lower() in ("buyer", "renter")


def _intent_present(data) -> bool:
    """Buying / renting / selling intent is confirmed, not merely implied."""
    purpose = str(data.get("purpose") or "").strip().lower()
    if purpose in ("buy", "purchase", "rent", "renting", "sell", "selling", "let"):
        return True
    lead_type = str(data.get("lead_type") or "").strip().lower()
    if lead_type in ("buyer", "renter", "seller"):
        return True
    # Legacy leads have no purpose/lead_type column — an explicit status of
    # Qualified/Closed also proves an intent was established with the client.
    status = str(data.get("status") or "").strip().lower()
    return status in ("qualified", "converted", "closed", "property matched")


def _timeline_days(data):
    """Normalise any timeline representation to a whole number of days.

    Accepts: timeline_days (int/str), timeline_label / timeline text with
    "30 days", "2 months", "within 3 months", "next year", "ASAP".
    Returns None when the timeline is genuinely unknown — never a guess.
    """
    raw = data.get("timeline_days")
    if raw not in (None, ""):
        try:
            days = int(float(str(raw).strip()))
            return max(0, days)
        except (TypeError, ValueError):
            pass

    text = " ".join(
        str(data.get(k) or "")
        for k in ("timeline_label", "timeline", "purchase_timeline")
    ).strip().lower()
    if not text:
        return None
    if any(w in text for w in ("asap", "immediately", "right away", "urgent")):
        return 0

    import re
    match = re.search(r"(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)", text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    factor = {"day": 1, "days": 1, "week": 7, "weeks": 7,
              "month": 30, "months": 30, "year": 365, "years": 365}[unit]
    return int(value * factor)


def _essential_preferences_present(data) -> bool:
    for key in ESSENTIAL_PREFERENCE_KEYS:
        if _has(data.get(key)):
            return True
    return False


# --------------------------------------------------------------------------- #
# The rules themselves — (key, label, points, predicate)
# --------------------------------------------------------------------------- #

def _rule_budget(data):
    return _budget_present(data)


def _rule_location(data):
    return _has(data.get("preferred_location"))


def _rule_type_or_bedrooms(data):
    return _type_or_bedrooms_present(data)


def _rule_intent(data):
    return _intent_present(data)


def _rule_essentials(data):
    return _essential_preferences_present(data)


def _rule_timeline(days, bands):
    """Exactly one timeline band applies (first match wins). Unknown -> 0."""
    if days is None:
        return 0, "timeline unknown — no points awarded"
    for limit, label, points in bands:
        if limit is None or days <= limit:
            return points, f"timeline {label} ({days} day{'s' if days != 1 else ''})"
    return 0, "timeline unknown — no points awarded"


QUALIFICATION_RULES = (
    ("budget", "Budget provided", 20, _rule_budget),
    ("location", "Preferred location provided", 20, _rule_location),
    ("type_or_bedrooms", "Property type or bedroom requirement provided", 15,
     _rule_type_or_bedrooms),
    ("intent", "Buying/renting intent confirmed", 15, _rule_intent),
    # timeline is handled separately (exclusive bands)
    ("essentials", "Essential preferences specified", 10, _rule_essentials),
)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def priority_for(score: int) -> str:
    """High >= 70, Medium 40-69, Low 0-39."""
    for label, threshold in PRIORITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "Low"


def score_lead(data, rules=None, timeline_bands=None):
    """Score one lead 0-100 with a full, explainable breakdown.

    Returns {'score', 'priority', 'breakdown': [{'key','label','points',
    'awarded','reason'}]}.
    """
    rules = rules if rules is not None else QUALIFICATION_RULES
    bands = timeline_bands if timeline_bands is not None else TIMELINE_BANDS

    breakdown = []
    total = 0

    for key, label, points, predicate in rules:
        try:
            awarded = bool(predicate(data))
        except (TypeError, ValueError):
            awarded = False
        total += points if awarded else 0
        breakdown.append({
            "key": key,
            "label": label,
            "points": points,
            "awarded": points if awarded else 0,
            "reason": f"{points} points awarded" if awarded
                      else "no points — information not provided",
        })

    # --- exclusive timeline band -------------------------------------------
    days = _timeline_days(data)
    timeline_points, timeline_reason = _rule_timeline(days, bands)
    timeline_rule_points = max((b[2] for b in bands), default=0)
    total += timeline_points
    breakdown.append({
        "key": "timeline",
        "label": "Purchase/rental timeline",
        "points": timeline_rule_points,
        "awarded": timeline_points,
        "reason": timeline_reason,
    })

    score = max(0, min(MAX_SCORE, int(total)))
    return {
        "score": score,
        "priority": priority_for(score),
        "breakdown": breakdown,
        "timeline_days": days,
    }
