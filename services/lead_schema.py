"""
services/lead_schema.py
FR-02 / FR-03 — the single definition of what an extracted lead looks like,
plus a strict backend validator that every AI response must pass.

Design rules (from the PRD):
  * Unknown values are ``None`` — the model may never guess.
  * Customer contact details are captured ONLY when the customer supplied
    them in the enquiry text.
  * Customer messages are untrusted input: the schema never executes or
    interprets them, it only stores them as data.
  * Validation never raises for bad model output — it returns
    ``(fields, errors, warnings)`` so the caller can degrade gracefully.

This module must NOT import database/app (pure data + validation).
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Field limits
# --------------------------------------------------------------------------- #

MAX_ENQUIRY_LENGTH = 4000
MIN_ENQUIRY_LENGTH = 10

LIMITS = {
    "customer_name": 120,
    "phone": 40,
    "email": 120,
    "preferred_location": 120,
    "property_type": 60,
    "currency": 12,
    "other_preferences": 500,
    "timeline_label": 60,
}

LEAD_TYPES = ("buyer", "renter", "seller", "enquiry")
PURPOSES = ("buy", "rent", "sell", "let")

MAX_AMENITIES = 20
MAX_QUESTIONS = 10
MAX_MISSING = 20
MAX_ROOMS = 50
MAX_BUDGET = 1_000_000_000_000  # sanity ceiling: 1 trillion


class EnquiryValidationError(ValueError):
    """Raised when the raw enquiry text itself is not usable."""


# --------------------------------------------------------------------------- #
# Default (server-derived) missing-information questions.
# Used when the model supplies none, and by the offline extractor.
# --------------------------------------------------------------------------- #

DEFAULT_QUESTIONS = {
    "budget": "What is your budget, and which currency should we use?",
    "preferred_location": "Which community or area are you interested in?",
    "property_type": "Are you looking for an apartment, villa, townhouse or studio?",
    "bedrooms": "How many bedrooms do you need?",
    "timeline": "When are you looking to move or complete the purchase?",
    "contact": "What is the best phone number or email to reach you on?",
}


def _is_missing(field_value) -> bool:
    if field_value is None:
        return True
    if isinstance(field_value, str) and not field_value.strip():
        return True
    if isinstance(field_value, (list, tuple)) and not field_value:
        return True
    return False


def empty_fields():
    """A fully-shaped, all-unknown extraction result."""
    return {
        "customer_name": None,
        "phone": None,
        "email": None,
        "lead_type": None,
        "property_type": None,
        "preferred_location": None,
        "bedrooms": None,
        "bathrooms": None,
        "budget_min": None,
        "budget_max": None,
        "currency": None,
        "purpose": None,
        "amenities": [],
        "other_preferences": None,
        "timeline_days": None,
        "timeline_label": None,
    }


# Fields whose absence should be surfaced to the agent.
REQUIRED_FOR_MATCHING = ("preferred_location", "budget_max", "property_type", "bedrooms")
NICE_TO_HAVE = ("timeline_days", "contact")


def derive_missing_and_questions(fields):
    """Server-side missing-information detection (FR-03).

    Deterministic — independent of any model, so it works for the offline
    path and as a safety net when the model returns an empty list.
    Returns (missing_fields, clarification_questions).
    """
    missing = []
    questions = []

    if _is_missing(fields.get("preferred_location")):
        missing.append("preferred_location")
        questions.append(DEFAULT_QUESTIONS["preferred_location"])
    if _is_missing(fields.get("budget_max")) and _is_missing(fields.get("budget_min")):
        missing.append("budget")
        questions.append(DEFAULT_QUESTIONS["budget"])
    if _is_missing(fields.get("property_type")):
        missing.append("property_type")
        questions.append(DEFAULT_QUESTIONS["property_type"])
    if _is_missing(fields.get("bedrooms")):
        missing.append("bedrooms")
        questions.append(DEFAULT_QUESTIONS["bedrooms"])
    if _is_missing(fields.get("timeline_days")):
        missing.append("timeline")
        questions.append(DEFAULT_QUESTIONS["timeline"])
    if (_is_missing(fields.get("phone")) and _is_missing(fields.get("email"))
            and _is_missing(fields.get("customer_name"))):
        missing.append("contact_details")
        questions.append(DEFAULT_QUESTIONS["contact"])

    return missing, questions


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _clean_text(value, max_len):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    return value[:max_len]


def _clean_int(value, field, errors, lo=0, hi=None):
    if value in (None, "", "null", "unknown"):
        return None
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        errors.append(f"{field} must be a number (got {value!r})")
        return None
    if number < lo or (hi is not None and number > hi):
        errors.append(f"{field} must be between {lo} and {hi} (got {number})")
        return None
    return number


def _clean_money(value, field, errors):
    if value in (None, "", "null", "unknown"):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("_", "").strip()
        value = re.sub(r"(?i)\b(aed|usd|eur|inr|gbp|dh)\b", "", value)
        suffixes = {"mn": "e5", "m": "e5", "million": "e5", "lakh": "e5",
                    "lac": "e5", "k": "e3", "bn": "e9", "billion": "e9"}
        value = re.sub(r"(?i)\b(mn|m|million|lakh|lac|k|bn|billion)\b",
                       lambda m: suffixes[m.group(0).lower()], value)
        value = re.sub(r"\s+", "", value)
        try:
            number = float(value)  # supports plain numbers and 1.5e5 forms
        except (TypeError, ValueError):
            errors.append(f"{field} must be a number (got {value[:40]!r})")
            return None
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        errors.append(f"{field} must be a number (got {value!r})")
        return None
    if number < 0:
        errors.append(f"{field} cannot be negative")
        return None
    if number > MAX_BUDGET:
        errors.append(f"{field} is implausibly large")
        return None
    return number


def _clean_choice(value, allowed, field, warnings):
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in allowed:
        return text
    # tolerate common synonyms without inventing anything
    synonyms = {
        "buying": "buy", "purchase": "buy", "purchasing": "buy", "for sale": "buy",
        "sale": "buy", "looking to buy": "buy",
        "renting": "rent", "rental": "rent", "lease": "rent", "for rent": "rent",
        "letting": "let", "to let": "let",
        "selling": "sell", "list": "sell", "listing": "sell",
        "looking for rent": "rent",
    }
    if text in synonyms and synonyms[text] in allowed:
        return synonyms[text]
    warnings.append(f"{field}: unknown value {str(value)[:40]!r} ignored (kept as unknown)")
    return None


def _clean_list(value, field, max_items, max_len, errors):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part for part in re.split(r"[,;]| and ", value) if part.strip()]
    if not isinstance(value, (list, tuple)):
        errors.append(f"{field} must be a list of short strings")
        return []
    out = []
    for item in list(value)[:max_items]:
        text = _clean_text(item, max_len)
        if text:
            out.append(text)
    if len(value) > max_items:
        errors.append(f"{field} has more than {max_items} entries — extras dropped")
    return out


_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{5,38}$")


# --------------------------------------------------------------------------- #
# Public validator
# --------------------------------------------------------------------------- #

def validate_extraction(payload):
    """Validate one raw model response.

    Returns ``(fields, errors, warnings)``:
      * ``fields``  — always a fully-shaped dict, unknown values are None,
      * ``errors``  — fatal problems (response not usable),
      * ``warnings``— recoverable problems (field ignored / corrected).

    Never raises.
    """
    fields = empty_fields()
    errors = []
    warnings = []

    if payload is None:
        return fields, ["response was empty"], warnings
    if not isinstance(payload, dict):
        return fields, [f"expected a JSON object, got {type(payload).__name__}"], warnings

    # Accept either a flat object or {"lead": {...}} / {"fields": {...}}
    for wrapper in ("lead", "fields", "extracted"):
        inner = payload.get(wrapper)
        if isinstance(inner, dict):
            payload = inner
            break

    # --- contact details: only meaningful when actually supplied -----------
    name = _clean_text(payload.get("customer_name") or payload.get("name"),
                       LIMITS["customer_name"])
    if name and len(name.split()) > 6:
        warnings.append("customer_name looks unusual — kept as supplied")
    fields["customer_name"] = name

    phone = _clean_text(payload.get("phone") or payload.get("telephone"),
                        LIMITS["phone"])
    if phone and not _PHONE_RE.match(phone):
        warnings.append("phone number does not look valid — kept as supplied")
    fields["phone"] = phone

    email = _clean_text(payload.get("email"), LIMITS["email"])
    if email and not _EMAIL_RE.match(email):
        warnings.append("email address does not look valid — kept as supplied")
    fields["email"] = email

    fields["lead_type"] = _clean_choice(payload.get("lead_type"), LEAD_TYPES,
                                        "lead_type", warnings)
    purpose = _clean_choice(payload.get("purpose"), PURPOSES, "purpose", warnings)
    fields["purpose"] = purpose

    # buyer/renter imply purpose when the model left it out (deterministic)
    if purpose is None and fields["lead_type"] in ("buyer", "renter", "seller"):
        fields["purpose"] = {"buyer": "buy", "renter": "rent",
                             "seller": "sell"}[fields["lead_type"]]

    fields["property_type"] = _clean_text(payload.get("property_type"),
                                          LIMITS["property_type"])
    fields["preferred_location"] = _clean_text(
        payload.get("preferred_location") or payload.get("location"),
        LIMITS["preferred_location"],
    )
    fields["currency"] = _clean_text(payload.get("currency"), LIMITS["currency"])
    fields["other_preferences"] = _clean_text(payload.get("other_preferences"),
                                              LIMITS["other_preferences"])
    fields["timeline_label"] = _clean_text(payload.get("timeline_label"),
                                           LIMITS["timeline_label"])

    fields["bedrooms"] = _clean_int(payload.get("bedrooms"), "bedrooms",
                                    errors, lo=0, hi=MAX_ROOMS)
    fields["bathrooms"] = _clean_int(payload.get("bathrooms"), "bathrooms",
                                     errors, lo=0, hi=MAX_ROOMS)

    fields["budget_min"] = _clean_money(payload.get("budget_min"), "budget_min", errors)
    fields["budget_max"] = _clean_money(
        payload.get("budget_max") or payload.get("budget"), "budget_max", errors)

    if (fields["budget_min"] is not None and fields["budget_max"] is not None
            and fields["budget_min"] > fields["budget_max"]):
        errors.append("budget_min cannot be greater than budget_max")
        fields["budget_min"], fields["budget_max"] = None, None

    fields["amenities"] = _clean_list(payload.get("amenities"), "amenities",
                                      MAX_AMENITIES, 60, errors)

    fields["timeline_days"] = _clean_int(payload.get("timeline_days"),
                                         "timeline_days", errors, lo=0, hi=3650 * 5)

    # Optional model-proposed extras — kept under reserved keys so the caller
    # can merge them; they are never trusted as facts, only as suggestions.
    fields["_clarification_questions"] = _clean_list(
        payload.get("clarification_questions"), "clarification_questions",
        MAX_QUESTIONS, 300, warnings)
    fields["_missing_information"] = _clean_list(
        payload.get("missing_information") or payload.get("missing_info"),
        "missing_information", MAX_MISSING, 80, warnings)

    return fields, errors, warnings


def validate_enquiry(text):
    """Validate the raw enquiry a human pasted. Raises EnquiryValidationError."""
    if text is None or not str(text).strip():
        raise EnquiryValidationError("Please paste or type the customer enquiry.")
    text = str(text)
    if len(text.strip()) < MIN_ENQUIRY_LENGTH:
        raise EnquiryValidationError(
            f"The enquiry is too short to analyse — please provide at least "
            f"{MIN_ENQUIRY_LENGTH} characters."
        )
    if len(text) > MAX_ENQUIRY_LENGTH:
        raise EnquiryValidationError(
            f"The enquiry is too long — maximum {MAX_ENQUIRY_LENGTH} characters "
            f"(you sent {len(text)}). Please shorten it."
        )
    return text.strip()
