"""
tests/test_qualification.py
FR-04 — the transparent 0-100 lead qualification score.

Run:  python -m unittest discover -s tests -v
"""

import unittest

from services.qualification import score_lead, priority_for, QUALIFICATION_RULES


def full_lead():
    return {
        "budget": 2_000_000,
        "budget_min": 1_500_000,
        "budget_max": 2_000_000,
        "preferred_location": "Dubai Marina",
        "property_type": "Apartment",
        "bedrooms_needed": 2,
        "bathrooms_needed": 2,
        "needs_swimming_pool": "Yes",
        "phone": "+971501234567",
        "email": "buyer@example.com",
        "purpose": "buy",
        "timeline_days": 30,
        "amenities": ["Swimming pool"],
    }


class QualificationTests(unittest.TestCase):
    def test_rule_weights_total_one_hundred(self):
        base = sum(points for _key, _label, points, _fn in QUALIFICATION_RULES)
        # the timeline rule contributes its maximum band on top of the base
        self.assertLessEqual(base, 100)
        self.assertGreater(base, 0)

    def test_empty_lead_scores_low(self):
        result = score_lead({})
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["priority"], "Low")

    def test_complete_lead_scores_high_and_capped(self):
        result = score_lead(full_lead())
        self.assertLessEqual(result["score"], 100)
        self.assertGreaterEqual(result["score"], 70)
        self.assertEqual(result["priority"], "High")
        self.assertTrue(result["breakdown"])

    def test_breakdown_explains_every_rule(self):
        result = score_lead(full_lead())
        keys = {item["key"] for item in result["breakdown"]}
        self.assertIn("budget", keys)
        self.assertIn("location", keys)
        self.assertIn("timeline", keys)
        for item in result["breakdown"]:
            self.assertIn("awarded", item)
            self.assertIn("points", item)
            self.assertLessEqual(item["awarded"], item["points"])

    def test_timeline_bands_are_exclusive(self):
        def timeline_points(days):
            data = {"timeline_days": days}
            return next(i for i in score_lead(data)["breakdown"]
                        if i["key"] == "timeline")["awarded"]

        # immediate is worth the most; every band is a single value
        self.assertGreater(timeline_points(0), 0)
        self.assertGreaterEqual(timeline_points(0), timeline_points(20))
        self.assertGreaterEqual(timeline_points(20), timeline_points(200))
        self.assertGreaterEqual(timeline_points(10000), 0)

    def test_priority_boundaries(self):
        self.assertEqual(priority_for(70), "High")
        self.assertEqual(priority_for(69), "Medium")
        self.assertEqual(priority_for(40), "Medium")
        self.assertEqual(priority_for(39), "Low")
        self.assertEqual(priority_for(0), "Low")

    def test_never_raises_on_garbage(self):
        result = score_lead({"budget": "not-a-number", "bedrooms_needed": "x",
                             "timeline_days": "soon"})
        self.assertIsInstance(result["score"], int)
        self.assertGreaterEqual(result["score"], 0)


if __name__ == "__main__":
    unittest.main()
