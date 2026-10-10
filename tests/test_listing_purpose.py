"""
tests/test_listing_purpose.py
Listing purpose (Sale/Rent) end to end:
  * the property form offers Sale / Rent (and a neutral "not set" for legacy),
  * add_property / update_property validate + persist the choice,
  * property cards and the detail page display the stored value,
  * the matcher never recommends an incompatible purpose,
  * unknown / unrecognised legacy values are shown as Unknown and never
    silently changed by an unrelated edit.

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import database  # noqa: E402
from database import add_property, update_property, get_property  # noqa: E402
from services.matching import match_properties  # noqa: E402
import app as app_module  # noqa: E402


def base_property(**overrides):
    data = {
        "name": "UNITTESTP Purpose Property",
        "location": "Dubai Marina",
        "price": "1000000",
        "bedrooms": "2",
        "bathrooms": "2",
        "property_type": "Apartment",
        "status": "Available",
        "has_swimming_pool": "No",
        "nearby_metro": "No",
    }
    data.update(overrides)
    return data


def _force_purpose(pid, value):
    """Set listing_purpose directly (models an imported/legacy row)."""
    conn = database.get_connection()
    try:
        conn.execute("UPDATE properties SET listing_purpose=? WHERE id=?",
                     (value, pid))
        conn.commit()
    finally:
        conn.close()


class PropertyPurposePersistenceTests(unittest.TestCase):
    def test_add_property_persists_sale(self):
        pid = add_property(base_property(listing_purpose="Sale"))
        self.addCleanup(database.delete_property, pid)
        self.assertEqual(get_property(pid)["listing_purpose"], "Sale")

    def test_add_property_persists_rent(self):
        pid = add_property(base_property(listing_purpose="Rent"))
        self.addCleanup(database.delete_property, pid)
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")

    def test_add_property_normalises_case(self):
        pid = add_property(base_property(listing_purpose="rEnT"))
        self.addCleanup(database.delete_property, pid)
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")

    def test_add_property_defaults_to_sale_when_omitted(self):
        data = base_property()
        data.pop("listing_purpose", None)
        pid = add_property(data)
        self.addCleanup(database.delete_property, pid)
        self.assertEqual(get_property(pid)["listing_purpose"], "Sale")

    def test_add_property_rejects_invalid_purpose(self):
        with self.assertRaises(ValueError):
            add_property(base_property(listing_purpose="Leasehold"))

    def test_update_property_changes_purpose(self):
        pid = add_property(base_property(listing_purpose="Sale"))
        self.addCleanup(database.delete_property, pid)
        update_property(pid, base_property(listing_purpose="Rent"))
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")

    def test_update_property_rejects_invalid_purpose(self):
        pid = add_property(base_property(listing_purpose="Sale"))
        self.addCleanup(database.delete_property, pid)
        with self.assertRaises(ValueError):
            update_property(pid, base_property(listing_purpose="Leasehold"))
        self.assertEqual(get_property(pid)["listing_purpose"], "Sale")

    def test_update_property_blank_preserves_existing(self):
        pid = add_property(base_property(listing_purpose="Rent"))
        self.addCleanup(database.delete_property, pid)
        update_property(pid, base_property(listing_purpose=""))
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")

    def test_update_property_absent_preserves_existing(self):
        pid = add_property(base_property(listing_purpose="Rent"))
        self.addCleanup(database.delete_property, pid)
        data = base_property()
        data.pop("listing_purpose", None)
        update_property(pid, data)
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")


class UnknownLegacyPurposeTests(unittest.TestCase):
    def _legacy(self, purpose):
        pid = add_property(base_property())
        self.addCleanup(database.delete_property, pid)
        _force_purpose(pid, purpose)
        return pid

    def test_null_purpose_survives_unrelated_edit(self):
        pid = self._legacy(None)
        update_property(pid, base_property(listing_purpose="",
                                           name="UNITTESTP Renamed"))
        prop = get_property(pid)
        self.assertIsNone(prop["listing_purpose"])
        self.assertEqual(prop["name"], "UNITTESTP Renamed")

    def test_unrecognised_value_is_preserved_and_shown_unknown(self):
        pid = self._legacy("Leasehold")
        kind, label = app_module._listing_purpose_display(
            get_property(pid)["listing_purpose"])
        self.assertEqual(kind, "unknown")
        self.assertNotIn(label, ("For Sale", "For Rent"))
        update_property(pid, base_property(listing_purpose=""))
        self.assertEqual(get_property(pid)["listing_purpose"], "Leasehold")

    def test_explicit_choice_overrides_unknown(self):
        pid = self._legacy(None)
        update_property(pid, base_property(listing_purpose="Rent"))
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")


class PropertyPurposeDisplayTests(unittest.TestCase):
    def setUp(self):
        self.client = helpers.client_for(["Super Admin"])

    def _make(self, name, purpose):
        pid = add_property(base_property(name=name, listing_purpose=purpose))
        self.addCleanup(database.delete_property, pid)
        return pid

    def test_detail_shows_for_sale(self):
        pid = self._make("UNITTESTP DetailA", "Sale")
        r = helpers.get(self.client, f"/properties/{pid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"For Sale", r.data)
        self.assertNotIn(b"For Rent", r.data)

    def test_detail_shows_for_rent(self):
        pid = self._make("UNITTESTP DetailB", "Rent")
        r = helpers.get(self.client, f"/properties/{pid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"For Rent", r.data)
        self.assertNotIn(b"For Sale", r.data)

    def test_detail_unknown_claims_neither(self):
        pid = self._make("UNITTESTP DetailC", "Sale")
        _force_purpose(pid, None)
        r = helpers.get(self.client, f"/properties/{pid}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b"For Sale", r.data)
        self.assertNotIn(b"For Rent", r.data)


class PropertyFormPurposeTests(unittest.TestCase):
    def setUp(self):
        self.client = helpers.client_for(["Super Admin"])

    def test_add_form_offers_sale_and_rent(self):
        r = helpers.get(self.client, "/properties/new")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'name="listing_purpose"', r.data)
        self.assertIn(b'value="Sale"', r.data)
        self.assertIn(b'value="Rent"', r.data)

    def test_edit_form_marks_stored_purpose(self):
        pid = add_property(base_property(name="UNITTESTP FormB",
                                         listing_purpose="Rent"))
        self.addCleanup(database.delete_property, pid)
        r = helpers.get(self.client, f"/properties/{pid}/edit")
        self.assertIn(b'value="Rent" selected', r.data)

    def test_create_through_form_persists_purpose(self):
        r = helpers.post(self.client, "/properties/new", data=base_property(
            name="UNITTESTP RouteRent", listing_purpose="Rent"))
        self.assertEqual(r.status_code, 302)
        prop = next(p for p in database.get_all_properties()
                    if p["name"] == "UNITTESTP RouteRent")
        self.addCleanup(database.delete_property, prop["id"])
        self.assertEqual(prop["listing_purpose"], "Rent")

    def test_edit_through_form_changes_purpose(self):
        pid = add_property(base_property(name="UNITTESTP RouteSale",
                                         listing_purpose="Sale"))
        self.addCleanup(database.delete_property, pid)
        r = helpers.post(self.client, f"/properties/{pid}/edit",
                         data=base_property(listing_purpose="Rent"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(get_property(pid)["listing_purpose"], "Rent")

    def test_invalid_purpose_via_form_is_rejected(self):
        r = helpers.post(self.client, "/properties/new", data=base_property(
            name="UNITTESTP BadPurpose", listing_purpose="Leasehold"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(any(p["name"] == "UNITTESTP BadPurpose"
                             for p in database.get_all_properties()))


class MatchingPurposeTests(unittest.TestCase):
    def _p(self, name, purpose):
        pid = add_property(base_property(name=name, listing_purpose=purpose))
        self.addCleanup(database.delete_property, pid)
        return get_property(pid)

    def test_sale_lead_never_gets_rent_listing(self):
        sale = self._p("UNITTESTP M1 Sale", "Sale")
        rent = self._p("UNITTESTP M1 Rent", "Rent")
        out = match_properties(
            {"purpose": "buy", "preferred_location": "Dubai Marina",
             "budget_max": 2_000_000},
            [sale, rent], limit=5,
        )
        ids = [r["property"]["id"] for r in out["results"]]
        self.assertIn(sale["id"], ids)
        self.assertNotIn(rent["id"], ids)

    def test_rent_lead_never_gets_sale_listing(self):
        sale = self._p("UNITTESTP M2 Sale", "Sale")
        rent = self._p("UNITTESTP M2 Rent", "Rent")
        out = match_properties(
            {"purpose": "rent", "preferred_location": "Dubai Marina",
             "budget_max": 2_000_000},
            [sale, rent], limit=5,
        )
        ids = [r["property"]["id"] for r in out["results"]]
        self.assertIn(rent["id"], ids)
        self.assertNotIn(sale["id"], ids)

    def test_unknown_purpose_listing_not_recommended_for_stated_purpose(self):
        unknown = self._p("UNITTESTP M3 Unknown", "Sale")
        _force_purpose(unknown["id"], None)
        unknown = get_property(unknown["id"])
        out = match_properties(
            {"purpose": "buy", "preferred_location": "Dubai Marina",
             "budget_max": 2_000_000},
            [unknown], limit=5,
        )
        self.assertEqual(out["results"], [])
        self.assertEqual(out["count_eligible"], 0)

    def test_unknown_lead_purpose_accepts_both(self):
        sale = self._p("UNITTESTP M4 Sale", "Sale")
        rent = self._p("UNITTESTP M4 Rent", "Rent")
        out = match_properties(
            {"preferred_location": "Dubai Marina", "budget_max": 2_000_000},
            [sale, rent], limit=5,
        )
        ids = [r["property"]["id"] for r in out["results"]]
        self.assertIn(sale["id"], ids)
        self.assertIn(rent["id"], ids)


if __name__ == "__main__":
    unittest.main()
