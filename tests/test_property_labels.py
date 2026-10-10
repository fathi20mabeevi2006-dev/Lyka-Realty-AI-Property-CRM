"""
tests/test_property_labels.py
R2 — property cards must show the deal label from the stored listing_purpose
(Sale -> "For Sale", Rent -> "For Rent"), and must NOT claim either when the
purpose is unknown or missing.

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import database  # noqa: E402
import app as app_module  # noqa: E402

TOKEN = "UNITTESTQZ"


def _card(**kwargs):
    base = {"id": 1, "name": "Listing", "location": "Dubai Marina",
            "price": 1_000_000, "bedrooms": 2, "bathrooms": 2,
            "status": "Available", "property_type": "Apartment"}
    base.update(kwargs)
    return base


class AnnotateListingCardTests(unittest.TestCase):
    """Unit-level: the label is derived from listing_purpose only."""

    def _annotate(self, **kwargs):
        card = _card(**kwargs)
        app_module._annotate_listing_cards([card])
        return card

    def test_sale_purpose_shows_for_sale(self):
        card = self._annotate(listing_purpose="Sale")
        self.assertEqual(card["listing_label"], "For Sale")
        self.assertEqual(card["listing_kind"], "sale")

    def test_rent_purpose_shows_for_rent(self):
        card = self._annotate(listing_purpose="Rent")
        self.assertEqual(card["listing_label"], "For Rent")
        self.assertEqual(card["listing_kind"], "rent")

    def test_purpose_is_not_confused_with_status(self):
        # A rent listing that is still "Available" must not read as "For Sale".
        card = self._annotate(listing_purpose="Rent", status="Available")
        self.assertEqual(card["listing_label"], "For Rent")
        # ... and a sale listing marked "Rented" must not read as "For Rent".
        card = self._annotate(listing_purpose="Sale", status="Rented")
        self.assertEqual(card["listing_label"], "For Sale")

    def test_unknown_purpose_claims_neither(self):
        for purpose in (None, "", "   ", "Leasehold?"):
            card = self._annotate(listing_purpose=purpose)
            self.assertEqual(card["listing_kind"], "unknown")
            self.assertNotIn(card["listing_label"], ("For Sale", "For Rent"))

    def test_missing_purpose_key_is_unknown(self):
        card = self._annotate()  # no listing_purpose key at all
        self.assertEqual(card["listing_kind"], "unknown")
        self.assertNotIn(card["listing_label"], ("For Sale", "For Rent"))


class PropertyCardRenderTests(unittest.TestCase):
    """End-to-end: the rendered grid reflects the stored purpose."""

    def setUp(self):
        self.client = helpers.client_for(["Super Admin"])

    def _make_property(self, name, listing_purpose):
        pid = database.add_property({
            "name": name, "location": "UNITTEST City", "price": "1000000",
            "bedrooms": "2", "bathrooms": "2", "status": "Available",
            "property_type": "Apartment",
        })
        self.addCleanup(database.delete_property, pid)
        conn = database.get_connection()
        try:
            conn.execute("UPDATE properties SET listing_purpose=? WHERE id=?",
                         (listing_purpose, pid))
            conn.commit()
        finally:
            conn.close()
        return pid

    def _card_html(self, token=TOKEN):
        r = helpers.get(self.client, f"/properties?q={token}")
        self.assertEqual(r.status_code, 200)
        return r.data

    def test_sale_card_renders_for_sale(self):
        self._make_property(f"{TOKEN} Sale Card", "Sale")
        html = self._card_html()
        self.assertIn(b"property-deal is-sale", html)
        self.assertIn(b"For Sale", html)
        self.assertNotIn(b"For Rent", html)

    def test_rent_card_renders_for_rent(self):
        self._make_property(f"{TOKEN} Rent Card", "Rent")
        html = self._card_html()
        self.assertIn(b"property-deal is-rent", html)
        self.assertIn(b"For Rent", html)
        self.assertNotIn(b"For Sale", html)

    def test_unknown_purpose_card_claims_neither(self):
        self._make_property(f"{TOKEN} Unknown Card", None)
        html = self._card_html()
        self.assertIn(b"property-deal is-unknown", html)
        self.assertNotIn(b"For Sale", html)
        self.assertNotIn(b"For Rent", html)


if __name__ == "__main__":
    unittest.main()
