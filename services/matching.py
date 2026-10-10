"""
services/matching.py
FR-06 — property matching / recommendation engine.

Everything here is DETERMINISTIC BACKEND LOGIC over real database rows:
no AI is consulted and no score is ever invented — the number in the result
is produced by the documented formula below.

Hard constraints (a property that fails one is never returned):
    * availability  — status must be 'Available'
    * purpose       — buy -> listing_purpose 'Sale', rent -> 'Rent'
                      (skipped only when the lead's purpose is genuinely
                      unknown: an unknown preference must not be assumed).
                      A listing whose own purpose is unknown/legacy is never
                      assumed to be Sale — it is excluded while a purpose is
                      required, since compatibility cannot be confirmed.
    * location      — when the lead named a location, a listing with no
                      overlap at all is never returned (the highest-weighted
                      criterion cannot be ignored)

Soft criteria and PRD weights:
    location ................ 30
    budget ................... 25
    property type ............ 10   } "property type and bedrooms" = 20
    bedrooms ................. 10   }
    amenities ................ 15
    area .....................  5   } "area and other preferences" = 10
    bathrooms ................  3   }
    other preferences ........  2   }

Score = 100 * sum(weight_i * score_i) / sum(weight_i for KNOWN criteria i)

A criterion the customer never mentioned is EXCLUDED and the remaining
weights are normalised — missing information never inflates or deflates a
score, and "unknown" is never treated as "no preference".

Every result carries human-readable `reasons` and `mismatches`.
"""

from __future__ import annotations

import json
import re

MATCH_WEIGHTS = {
    "location": 30,
    "budget": 25,
    "property_type": 10,
    "bedrooms": 10,
    "amenities": 15,
    "area": 5,
    "bathrooms": 3,
    "other": 2,
}

DEFAULT_LIMIT = 3
MIN_MATCH_SCORE = 30          # below this a candidate is not "suitable"
ENGINE_VERSION = "1.0"

SQM_TO_SQFT = 10.7639

# amenity label -> matcher
_AMENITY_ALIASES = {
    "swimming pool": ("pool", "swimming pool"),
    "pool": ("pool", "swimming pool"),
    "nearby metro": ("metro",),
    "metro": ("metro",),
    "gym": ("gym", "fitness"),
    "parking": ("parking", "garage"),
    "covered parking": ("parking", "garage"),
    "sea view": ("sea view", "beach", "marina view", "ocean"),
    "balcony": ("balcony", "terrace"),
    "garden": ("garden", "landscaped"),
    "furnished": ("furnished",),
    "private pool": ("private pool",),
    "maid's room": ("maid", "helper"),
    "elevator": ("elevator", "lift"),
    "security": ("security", "cctv"),
}


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _property_area_sqft(prop):
    """Area in square feet, preferring the dedicated column."""
    raw = prop.get("area_sqft")
    if raw not in (None, ""):
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    size = prop.get("property_size")
    if size not in (None, ""):
        try:
            # historical rows record metric size ("Size: 751 sqm")
            return float(size) * SQM_TO_SQFT
        except (TypeError, ValueError):
            pass
    text = str(prop.get("property_view") or "")
    if "sqm" in text.lower():
        match = re.search(r"([\d.]+)\s*sqm", text, re.I)
        if match:
            try:
                return float(match.group(1)) * SQM_TO_SQFT
            except ValueError:
                return None
    return None


def _property_amenities(prop):
    raw = prop.get("amenities")
    items = []
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = [str(i) for i in parsed]
        except json.JSONDecodeError:
            items = [p.strip() for p in raw.split(",") if p.strip()]
    return [_norm(i) for i in items]


def normalise_criteria(data):
    """Map a lead / request dict onto the matcher's criterion names."""
    amenities = data.get("amenities") or []
    if isinstance(amenities, str):
        amenities = [a for a in amenities.split(",") if a.strip()]

    def _yn(value):
        return str(value or "").strip().lower() in ("yes", "y", "true", "1")

    if _yn(data.get("needs_swimming_pool")) and not any(
            "pool" in _norm(a) for a in amenities):
        amenities = list(amenities) + ["Swimming pool"]
    if _yn(data.get("needs_nearby_metro")) and not any(
            "metro" in _norm(a) for a in amenities):
        amenities = list(amenities) + ["Nearby metro"]

    purpose = _norm(data.get("purpose")) or None
    if purpose in ("buying", "purchase"):
        purpose = "buy"
    if purpose in ("renting", "lease"):
        purpose = "rent"
    if purpose in ("selling",):
        purpose = "sell"
    listing_purpose = {"buy": "Sale", "rent": "Rent"}.get(purpose)

    def _num(*keys):
        for key in keys:
            value = data.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return None

    return {
        "purpose": purpose,
        "listing_purpose": listing_purpose,
        "location": (data.get("preferred_location") or data.get("location") or "").strip(),
        "property_type": (data.get("property_type") or "").strip(),
        "bedrooms": int(data["bedrooms_needed"]) if data.get("bedrooms_needed") not in (None, "")
        else (int(data["bedrooms"]) if data.get("bedrooms") not in (None, "") else None),
        "bathrooms": int(data.get("bathrooms") or data.get("bathrooms_needed"))
        if data.get("bathrooms") not in (None, "") or data.get("bathrooms_needed") not in (None, "")
        else None,
        "budget": _num("budget", "budget_max"),
        "budget_max": _num("budget_max", "budget"),
        "budget_min": _num("budget_min"),
        "amenities": [str(a).strip() for a in amenities if str(a).strip()],
        "min_area": _num("min_area", "min_size"),
        "max_area": _num("max_area", "max_size"),
        "property_view": (data.get("property_view") or "").strip(),
        "floor_number": data.get("floor_number"),
    }


# --------------------------------------------------------------------------- #
# Per-criterion scoring (each returns 0.0 .. 1.0 plus reason/mismatch text)
# --------------------------------------------------------------------------- #

def _score_location(criteria, prop):
    wanted = _norm(criteria["location"])
    have = _norm(prop.get("location"))
    if not wanted:
        return None
    if not have:
        return 0.0, None, "location not recorded on the listing"
    if wanted in have or have in wanted:
        return 1.0, f"Location matches: {prop.get('location')}", None
    wanted_tokens = set(wanted.split())
    have_tokens = set(have.split())
    if wanted_tokens & have_tokens:
        overlap = sorted(wanted_tokens & have_tokens)
        return 0.6, f"Location related: {' '.join(overlap)}", None
    return 0.0, None, f"Located in {str(prop.get('location')).strip()}, not {criteria['location']}"


def _score_budget(criteria, prop):
    if criteria["budget_max"] is None and criteria["budget_min"] is None:
        return None
    price = prop.get("price")
    if price in (None, "", 0):
        return 0.0, None, "listing price not recorded"
    price = float(price)
    max_budget = criteria["budget_max"]
    min_budget = criteria["budget_min"]

    if min_budget is not None and price < min_budget:
        return (0.5,
                None,
                f"Price {price:,.0f} is below the stated minimum {min_budget:,.0f}")
    if max_budget is not None:
        if price <= max_budget:
            return 1.0, f"Within budget ({price:,.0f} <= {max_budget:,.0f})", None
        overshoot = (price - max_budget) / max_budget
        if overshoot <= 0.10:
            return 0.6, None, f"Price {price:,.0f} is {overshoot * 100:.0f}% above budget"
        if overshoot <= 0.25:
            return 0.3, None, f"Price {price:,.0f} is {overshoot * 100:.0f}% above budget"
        return 0.0, None, f"Price {price:,.0f} is {overshoot * 100:.0f}% above budget"
    return 0.5, None, "no maximum budget stated"


def _score_type(criteria, prop):
    wanted = _norm(criteria["property_type"])
    if not wanted:
        return None
    have = _norm(prop.get("property_type"))
    if not have:
        return 0.5, None, "property type not recorded on the listing"
    if wanted == have or wanted in have or have in wanted:
        return 1.0, f"Type matches: {prop.get('property_type')}", None
    return 0.0, None, f"Type is {prop.get('property_type')}, not {criteria['property_type']}"


def _score_bedrooms(criteria, prop):
    wanted = criteria["bedrooms"]
    if wanted is None:
        return None
    have = prop.get("bedrooms")
    if have in (None, ""):
        return 0.5, None, "bedroom count not recorded"
    have = int(have)
    if have == wanted:
        return 1.0, f"{have} bedroom{'s' if have != 1 else ''} as requested", None
    if have > wanted:
        return 0.7, f"{have} bedrooms (more than the {wanted} requested)", None
    if have == wanted - 1:
        return 0.4, None, f"Only {have} bedrooms ({wanted} requested)"
    return 0.0, None, f"Only {have} bedrooms ({wanted} requested)"


def _score_amenities(criteria, prop):
    wanted = criteria["amenities"]
    if not wanted:
        return None
    available = _property_amenities(prop)
    blob = " ".join([
        " ".join(available),
        _norm(prop.get("has_swimming_pool")),
        _norm(prop.get("nearby_metro")),
        _norm(prop.get("name")),
        _norm(prop.get("property_view")),
    ])
    if _norm(prop.get("has_swimming_pool")) == "yes":
        blob += " pool swimming"
    if _norm(prop.get("nearby_metro")) == "yes":
        blob += " metro"

    matched, missing = [], []
    for item in wanted:
        keys = _AMENITY_ALIASES.get(_norm(item), (_norm(item),))
        if any(key and key in blob for key in keys):
            matched.append(item)
        else:
            missing.append(item)

    score = len(matched) / len(wanted) if wanted else 0.0
    reason = None
    mismatch = None
    if matched:
        reason = "Amenities matched: " + ", ".join(matched)
    if missing:
        mismatch = "Missing requested: " + ", ".join(missing)
    return score, reason, mismatch


def _score_area(criteria, prop):
    if criteria["min_area"] is None and criteria["max_area"] is None:
        return None
    area = _property_area_sqft(prop)
    if area is None:
        return 0.5, None, "floor area not recorded"
    lo, hi = criteria["min_area"], criteria["max_area"]
    if lo is not None and area < lo:
        return 0.4, None, f"{area:,.0f} sq ft is smaller than the {lo:,.0f} sq ft minimum"
    if hi is not None and area > hi:
        return 0.4, None, f"{area:,.0f} sq ft is larger than the {hi:,.0f} sq ft maximum"
    return 1.0, f"{area:,.0f} sq ft within the requested range", None


def _score_bathrooms(criteria, prop):
    wanted = criteria["bathrooms"]
    if wanted is None:
        return None
    have = prop.get("bathrooms")
    if have in (None, ""):
        return 0.5, None, "bathroom count not recorded"
    have = int(have)
    if have >= wanted:
        return 1.0, f"{have} bathrooms (>= {wanted} requested)", None
    return 0.3, None, f"Only {have} bathrooms ({wanted} requested)"


def _score_other(criteria, prop):
    if not criteria["property_view"] and criteria["floor_number"] in (None, ""):
        return None
    score, reasons, mismatches = 1.0, [], []
    if criteria["property_view"]:
        if _norm(criteria["property_view"]) == _norm(prop.get("property_view")):
            reasons.append(f"View: {prop.get('property_view')}")
        else:
            score -= 0.5
            mismatches.append(
                f"View is {prop.get('property_view') or 'not recorded'}, "
                f"not {criteria['property_view']}")
    if criteria["floor_number"] not in (None, ""):
        try:
            wanted_floor = int(criteria["floor_number"])
            have_floor = int(prop.get("floor_number") or -1)
            if have_floor == wanted_floor:
                reasons.append(f"Floor {have_floor}")
            else:
                score -= 0.5
                mismatches.append(f"Floor {have_floor if have_floor >= 0 else 'n/a'} "
                                  f"vs requested {wanted_floor}")
        except (TypeError, ValueError):
            pass
    score = max(0.0, min(1.0, score))
    return score, ("; ".join(reasons) or None), ("; ".join(mismatches) or None)


_CRITERIA = (
    ("location", _score_location),
    ("budget", _score_budget),
    ("property_type", _score_type),
    ("bedrooms", _score_bedrooms),
    ("amenities", _score_amenities),
    ("area", _score_area),
    ("bathrooms", _score_bathrooms),
    ("other", _score_other),
)


def score_property(criteria, prop):
    """Score one property against the criteria → (score, reasons, mismatches)."""
    weighted = 0.0
    known_weight = 0
    reasons, mismatches = [], []

    for key, fn in _CRITERIA:
        weight = MATCH_WEIGHTS[key]
        result = fn(criteria, prop)
        if result is None:
            continue                       # criterion unknown -> excluded
        value, reason, mismatch = result
        weighted += weight * value
        known_weight += weight
        if reason:
            reasons.append(reason)
        if mismatch:
            mismatches.append(mismatch)

    if known_weight == 0:
        return 0, [], ["no comparable criteria were provided"]
    score = int(round(100.0 * weighted / known_weight))
    return max(0, min(100, score)), reasons, mismatches


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def match_properties(criteria_data, properties, limit=DEFAULT_LIMIT,
                     weights=None, min_score=MIN_MATCH_SCORE):
    """Rank `properties` (list of dicts) against `criteria_data`.

    Returns:
      {
        "results": [ {property, match_score, reasons, mismatches} ... ],
        "count_considered": int, "count_eligible": int,
        "no_match": bool, "message": str, "weights": {...}, "engine": ...,
        "hard_filters": {...}
      }
    """
    criteria = normalise_criteria(criteria_data)
    hard_filters = {
        "availability": "Available",
        "purpose": criteria["listing_purpose"] or "not specified",
        "location": criteria["location"] or "any",
    }

    eligible = []
    for prop in properties:
        if str(prop.get("status") or "").strip() != "Available":
            continue
        if criteria["listing_purpose"]:
            # Exact match on the stored purpose. A listing whose purpose is
            # unknown/legacy (NULL, empty, or an unrecognised value) is NOT
            # assumed to be for sale — it is left out because we cannot confirm
            # it is compatible with the stated Sale/Rent requirement.
            prop_purpose = str(prop.get("listing_purpose") or "").strip().lower()
            if prop_purpose != criteria["listing_purpose"].lower():
                continue
        eligible.append(prop)

    scored = []
    location_excluded = 0
    for prop in eligible:
        score, reasons, mismatches = score_property(criteria, prop)
        # A requested location with no overlap at all is not a "suitable"
        # property, however well it scores elsewhere (PRD: location is the
        # highest-weighted criterion). Such candidates are never returned.
        if criteria["location"]:
            location_check = _score_location(criteria, prop)
            if location_check is not None and location_check[0] == 0.0:
                location_excluded += 1
                continue
        if score < min_score:
            continue
        scored.append((score, prop, reasons, mismatches))

    scored.sort(key=lambda item: (item[0], item[1].get("id") or 0), reverse=True)
    top = scored[: max(0, int(limit))]

    results = [
        {
            "property": prop,
            "match_score": score,
            "reasons": reasons,
            "mismatches": mismatches,
        }
        for score, prop, reasons, mismatches in top
    ]

    if results:
        message = (f"{len(results)} matching "
                   f"propert{'y' if len(results) == 1 else 'ies'} found.")
    elif not eligible:
        message = ("No available properties match the required purpose and "
                   "availability, so nothing can be recommended.")
    elif location_excluded and not scored:
        message = (f"No available property in \"{criteria['location']}\" "
                   f"met the requirements, so no recommendation is possible.")
    elif scored:
        message = "No property reached the minimum match score."
    else:
        best = None
        for prop in eligible:
            score, _, _ = score_property(criteria, prop)
            best = score if best is None else max(best, score)
        message = (f"No suitable match found (best candidate scored "
                   f"{best if best is not None else 0}/100, threshold "
                   f"{min_score}).")

    return {
        "results": results,
        "count_considered": len(properties),
        "count_eligible": len(eligible),
        "count_location_excluded": location_excluded,
        "no_match": not results,
        "message": message,
        "weights": dict(weights or MATCH_WEIGHTS),
        "engine": ENGINE_VERSION,
        "hard_filters": hard_filters,
        "criteria": criteria,
        "threshold": min_score,
    }
