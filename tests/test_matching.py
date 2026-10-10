"""
tests/test_matching.py
FR-06 — deterministic property matching / recommendations.

Run:  python -m unittest discover -s tests -v
"""

import json
import unittest

import helpers  # noqa: E402
from helpers import database  # noqa: E402
from services.matching import (  # noqa: E402
    match_properties, normalise_criteria, score_property, MATCH_WEIGHTS,
)


def prop(**kwargs):
    base = {
        "id": 1, "name": "Listing", "location": "Dubai Marina",
        "price": 1_800_000, "bedrooms": 2, "bathrooms": 2,
        "property_type": "Apartment", "listing_purpose": "Sale",
        "status": "Available", "amenities": json.dumps(["Swimming pool", "Nearby metro"]),
        "has_swimming_pool": "Yes", "nearby_metro": "Yes", "area_sqft": 1200,
    }
    base.update(kwargs)
    return base


class MatchingUnitTests(unittest.TestCase):
    def test_normalise_criteria_maps_purpose(self):
        crit = normalise_criteria({"purpose": "buying", "bedrooms": 3})
        self.assertEqual(crit["listing_purpose"], "Sale")
        crit = normalise_criteria({"purpose": "renting"})
        self.assertEqual(crit["listing_purpose"], "Rent")

    def test_purpose_is_a_hard_filter(self):
        rent_lead = {"purpose": "rent", "preferred_location": "Dubai Marina"}
        out = match_properties(rent_lead, [prop(listing_purpose="Sale")], limit=3)
        self.assertEqual(out["count_eligible"], 0)
        self.assertTrue(out["no_match"])

    def test_unavailable_listings_are_never_returned(self):
        out = match_properties({"preferred_location": "Dubai Marina"},
                               [prop(status="Sold"), prop(status="Rented")], limit=3)
        self.assertEqual(out["count_eligible"], 0)
        self.assertTrue(out["no_match"])

    def test_wrong_location_is_not_a_match(self):
        out = match_properties(
            {"preferred_location": "Nowhereville", "budget_max": 2_000_000},
            [prop()], limit=3,
        )
        self.assertTrue(out["no_match"])

    def test_unknown_criteria_excluded_not_penalised(self):
        # lead only states location -> score reflects location alone
        score, reasons, mismatches = score_property(
            normalise_criteria({"preferred_location": "Dubai Marina"}), prop())
        self.assertEqual(score, 100)

    def test_budget_over_threshold_scores_lower(self):
        lead = normalise_criteria({"budget_max": 1_000_000})
        score, _reasons, mismatches = score_property(lead, prop(price=1_800_000))
        self.assertLess(score, 100)
        self.assertTrue(mismatches)

    def test_weights_include_location_and_budget(self):
        self.assertIn("location", MATCH_WEIGHTS)
        self.assertIn("budget", MATCH_WEIGHTS)
        self.assertEqual(max(MATCH_WEIGHTS, key=MATCH_WEIGHTS.get), "location")

    def test_empty_criteria_is_honest_no_match(self):
        out = match_properties({}, [prop()], limit=3)
        self.assertTrue(out["no_match"])
        self.assertIn("No suitable match", out["message"])


class MatchingIntegrationTests(unittest.TestCase):
    """Runs against the disposable DB copy (includes demo Sale + Rent rows)."""

    def test_sale_lead_gets_sale_listings(self):
        lead = database.add_lead({
            "client_name": "UNITTEST Match Sale", "preferred_location": "Dubai Marina",
            "bedrooms_needed": 2, "property_type": "Apartment", "purpose": "buy",
            "budget_min": 1_500_000, "budget_max": 2_000_000,
            "amenities": "Swimming pool, Nearby metro",
        })
        try:
            out = match_properties(database.get_lead(lead),
                                   database.get_all_properties(), limit=3)
            self.assertTrue(out["results"])
            for item in out["results"]:
                self.assertEqual(item["property"]["listing_purpose"], "Sale")
                self.assertEqual(item["property"]["status"], "Available")
                self.assertGreaterEqual(item["match_score"], out["threshold"])
        finally:
            database.delete_lead(lead)

    def test_recommendations_persist_and_history_grows(self):
        lead = database.add_lead({
            "client_name": "UNITTEST Match Persist", "preferred_location": "Dubai Marina",
            "bedrooms_needed": 1, "purpose": "rent", "budget_max": 100000,
        })
        try:
            lead_row = database.get_lead(lead)
            out = match_properties(lead_row, database.get_all_properties(), limit=3)
            database.save_recommendations(lead, out["results"], engine_version=out["engine"])
            self.assertTrue(out["results"])
            latest = database.get_latest_recommendations(lead)
            self.assertEqual(len(latest), len(out["results"]))
            self.assertIsInstance(latest[0]["reasons"], list)
            self.assertIsInstance(latest[0]["snapshot"], dict)
            self.assertIn("name", latest[0]["snapshot"])
        finally:
            database.delete_lead(lead)


if __name__ == "__main__":
    unittest.main()
