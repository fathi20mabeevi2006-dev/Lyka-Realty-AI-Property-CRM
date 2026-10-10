"""
tests/test_rbac.py
Phase 2 — backend-enforced role based access control.

Covers permission gates (403s), lead row-level ownership rules, and client
lead scoping. All requests carry valid sessions + CSRF tokens, so any 403
here is a genuine authorization decision (not a login/CSRF side effect).

Run:  python -m unittest discover -s tests -v
"""

import unittest

import helpers  # noqa: E402
from helpers import database  # noqa: E402

SALES = ["Sales/CRM"]
CLIENT = ["Client"]
MARKETING = ["Marketing"]
FINANCE = ["Finance/Accounts"]
PROPERTY_ROLE = ["Property/Operations"]
COMPANY_ADMIN = ["Company Admin"]
SUPER_ADMIN = ["Super Admin"]
PASSWORD = "UnittestPass1!"


class RBACTests(unittest.TestCase):
    # ---------------------------------------------------------------- admin
    def test_super_admin_can_manage_users_and_audit(self):
        client = helpers.client_for(SUPER_ADMIN)
        self.assertEqual(helpers.get(client, "/admin/users").status_code, 200)
        self.assertEqual(helpers.get(client, "/admin/audit").status_code, 200)

    def test_company_admin_can_view_audit_but_not_manage_users(self):
        client = helpers.client_for(COMPANY_ADMIN)
        self.assertEqual(helpers.get(client, "/admin/audit").status_code, 200)
        self.assertEqual(helpers.get(client, "/admin/users").status_code, 403)

    # ------------------------------------------------------------- sales role
    def test_sales_permission_gates(self):
        client = helpers.client_for(SALES)
        self.assertEqual(helpers.get(client, "/leads").status_code, 200)
        self.assertEqual(helpers.get(client, "/leads/new").status_code, 200)
        self.assertEqual(helpers.get(client, "/assistant").status_code, 200)
        self.assertEqual(helpers.get(client, "/brd").status_code, 200)
        self.assertEqual(helpers.get(client, "/properties/new").status_code, 403)
        self.assertEqual(helpers.get(client, "/admin/users").status_code, 403)

    def test_sales_auto_owns_created_lead(self):
        client = helpers.client_for(SALES)
        r = helpers.post(client, "/leads/new", data={
            "client_name": f"UNITTEST Sales Owned {__name__}",
            "budget": "800000", "bedrooms_needed": "2",
            "phone": "0500000000",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        lead = next(x for x in database.get_all_leads()
                    if x["client_name"].startswith("UNITTEST Sales Owned"))
        try:
            self.assertIsNotNone(lead["owner_user_id"])
        finally:
            database.delete_lead(lead["id"])

    def test_sales_can_edit_own_but_not_others_lead(self):
        sales = helpers.client_for(SALES)
        owner = helpers.current_user(sales)
        other = helpers.make_user("sales_other_owner")
        mine = database.add_lead({
            "client_name": "UNITTEST Mine Lead", "budget": "100",
            "owner_user_id": owner["id"]})
        theirs = database.add_lead({
            "client_name": "UNITTEST Theirs Lead", "budget": "100",
            "owner_user_id": other["id"]})
        unassigned = database.add_lead({
            "client_name": "UNITTEST Unassigned Lead", "budget": "100",
            "owner_user_id": None})
        try:
            self.assertEqual(
                helpers.get(sales, f"/leads/{mine}/edit").status_code, 200)
            self.assertEqual(
                helpers.get(sales, f"/leads/{theirs}/edit").status_code, 403)
            self.assertEqual(
                helpers.get(sales, f"/leads/{unassigned}/edit").status_code, 200)

            # delete requires leads.delete → no sales role holds it
            self.assertEqual(
                helpers.post(sales, f"/leads/{mine}/delete").status_code, 403)
        finally:
            for lid in (mine, theirs, unassigned):
                database.delete_lead(lid)

    def test_sales_cannot_change_others_lead_status(self):
        sales = helpers.client_for(SALES)
        other = helpers.make_user("sales_other_status")
        theirs = database.add_lead({
            "client_name": "UNITTEST Their Status", "budget": "100",
            "owner_user_id": other["id"]})
        try:
            self.assertEqual(helpers.post(
                sales, f"/leads/{theirs}/status",
                data={"status": "Qualified"}).status_code, 403)
        finally:
            database.delete_lead(theirs)

    def test_sales_edit_does_not_wipe_ownership(self):
        sales = helpers.client_for(SALES)
        owner = helpers.current_user(sales)
        lid = database.add_lead({
            "client_name": "UNITTEST Ownership Keep", "budget": "100",
            "phone": "0501111111", "owner_user_id": owner["id"]})
        try:
            helpers.post(sales, f"/leads/{lid}/edit", data={
                "client_name": "UNITTEST Ownership Keep",
                "budget": "200", "phone": "0502222222",
            }, follow_redirects=True)
            self.assertEqual(database.get_lead(lid)["owner_user_id"], owner["id"])
        finally:
            database.delete_lead(lid)

    # ----------------------------------------------------------- client role
    def test_client_portal_restrictions(self):
        client = helpers.client_for(CLIENT)
        html = helpers.get(client, "/").get_data(as_text=True)
        self.assertIn("My Dashboard", html)  # client dashboard variant
        self.assertEqual(helpers.get(client, "/assistant").status_code, 403)
        self.assertEqual(helpers.get(client, "/leads/new").status_code, 403)
        self.assertEqual(helpers.get(client, "/brd").status_code, 403)
        self.assertEqual(
            helpers.post(client, "/api/assistant",
                         json={"message": "hi"}).status_code, 403)

    def test_client_sees_only_own_leads(self):
        client_user = helpers.make_user("client_scope_see", roles=CLIENT,
                                        full_name="Scope Client")
        client = helpers.client_for(CLIENT, username="client_scope_see")
        mine = database.add_lead({
            "client_name": "UNITTEST Client Own Lead", "budget": "100",
            "client_user_id": client_user["id"]})
        other = database.add_lead({
            "client_name": "UNITTEST Other Client Lead", "budget": "100",
            "client_user_id": None})
        try:
            html = helpers.get(client, "/leads").get_data(as_text=True)
            self.assertIn("UNITTEST Client Own Lead", html)
            self.assertNotIn("UNITTEST Other Client Lead", html)
            # ...and row-level edit denial for leads that are not theirs
            self.assertEqual(
                helpers.get(client, f"/leads/{other}/edit").status_code, 403)
        finally:
            database.delete_lead(mine)
            database.delete_lead(other)

    # -------------------------------------------------- other staff roles
    def test_marketing_can_create_unowned_lead(self):
        client = helpers.client_for(MARKETING)
        r = helpers.post(client, "/leads/new", data={
            "client_name": "UNITTEST Mktg Lead",
            "budget": "123456", "bedrooms_needed": "3",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        lead = next(x for x in database.get_all_leads()
                    if x["client_name"] == "UNITTEST Mktg Lead")
        try:
            self.assertIsNone(lead["owner_user_id"])
            self.assertEqual(helpers.get(client, "/properties/new").status_code, 403)
        finally:
            database.delete_lead(lead["id"])

    def test_finance_has_no_leads_access(self):
        client = helpers.client_for(FINANCE)
        self.assertEqual(helpers.get(client, "/leads").status_code, 403)
        self.assertEqual(helpers.get(client, "/assistant").status_code, 200)
        self.assertEqual(helpers.get(client, "/properties").status_code, 200)

    def test_property_role_can_manage_listings(self):
        client = helpers.client_for(PROPERTY_ROLE)
        self.assertEqual(helpers.get(client, "/properties/new").status_code, 200)
        pid = database.add_property({
            "name": "UNITTEST Ops Property", "location": "Dubai",
            "price": "100", "bedrooms": "1", "bathrooms": "1",
            "status": "Available"})
        try:
            self.assertEqual(
                helpers.get(client, f"/properties/{pid}/edit").status_code, 200)
            # but cannot delete listings (admin-only)
            self.assertEqual(
                helpers.post(client, f"/properties/{pid}/delete").status_code, 403)
        finally:
            database.delete_property(pid)

    # ------------------------------------------------- property delete gates
    def test_property_delete_is_super_admin_only(self):
        pid = database.add_property({
            "name": "UNITTEST Delete Gate", "location": "Dubai",
            "price": "100", "bedrooms": "1", "bathrooms": "1",
            "status": "Available"})
        try:
            company_admin = helpers.client_for(COMPANY_ADMIN)
            self.assertEqual(
                helpers.post(company_admin,
                             f"/properties/{pid}/delete").status_code, 403)

            super_admin = helpers.client_for(SUPER_ADMIN)
            r = helpers.post(super_admin, f"/properties/{pid}/delete")
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.headers.get("Location", "").endswith("/properties"))
            self.assertIsNone(database.get_property(pid))
        finally:
            database.delete_property(pid)


def id_from_client(client):
    """Current user id for a logged-in test client (reads its session)."""
    return helpers.current_user(client)["id"] if helpers.current_user(client) else None


if __name__ == "__main__":
    unittest.main(verbosity=2)