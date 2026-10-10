"""
manage_users.py — command-line user management (Phase 2).

Run from the project folder. Every command prompts for passwords at the
terminal (they are never passed on the command line, so they don't end up
in shell history).

Examples:
    python manage_users.py create-admin alice
    python manage_users.py create-user bob --roles "Sales/CRM" --full-name "Bob Smith"
    python manage_users.py list
    python manage_users.py reset-password alice
    python manage_users.py status alice Suspended
"""

import argparse
import getpass
import sys

from werkzeug.security import check_password_hash, generate_password_hash

import database

MIN_PASSWORD_LENGTH = 8


def _read_password(prompt="Password (hidden): "):
    while True:
        value = getpass.getpass(prompt)
        if len(value) >= MIN_PASSWORD_LENGTH:
            return value
        print(f"  Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def cmd_create_admin(args):
    database.bootstrap_roles()
    username = args.username.strip()
    if database.get_user_by_username(username):
        print(f"User '{username}' already exists.")
        return 1
    password = _read_password()
    user_id = database.create_user(
        username=username,
        password_hash=generate_password_hash(password),
        full_name=args.full_name,
        email=args.email,
        department=args.department,
        roles=["Super Admin"],
    )
    database.add_audit_log("user.create", user_id=user_id,
                           details="created via manage_users CLI (Super Admin)")
    print(f"Super Admin '{username}' created (user id {user_id}).")
    return 0


def cmd_create_user(args):
    database.bootstrap_roles()
    username = args.username.strip()
    if database.get_user_by_username(username):
        print(f"User '{username}' already exists.")
        return 1

    available = set(database.role_names())
    roles = [r for r in (args.roles or []) if r in available]
    if not roles:
        print(f"  No valid roles chosen. Available: {sorted(available)}")
        return 1

    password = _read_password()
    user_id = database.create_user(
        username=username,
        password_hash=generate_password_hash(password),
        full_name=args.full_name,
        email=args.email,
        department=args.department,
        roles=roles,
        status=args.status,
    )
    database.add_audit_log("user.create", user_id=user_id,
                           details=f"created via manage_users CLI (roles={roles})")
    print(f"User '{username}' created (user id {user_id}) with roles {roles}.")
    return 0


def cmd_list(_args):
    users = database.list_users()
    if not users:
        print("No users yet.")
        return 0
    for u in users:
        roles = ", ".join(database.get_user_roles(u["id"])) or "(none)"
        print(f"{u['id']:<4} {u['username']:<20} {u['status']:<10} {roles}")
    return 0


def cmd_reset_password(args):
    user = _get_user(args.username)
    if not user:
        return 1
    password = _read_password("New password (hidden): ")
    database.set_user_password(user["id"], generate_password_hash(password))
    database.add_audit_log("user.password_reset", user_id=user["id"],
                           details="reset via manage_users CLI")
    print(f"Password reset for '{user['username']}'.")
    return 0


def cmd_status(args):
    user = _get_user(args.username)
    if not user:
        return 1
    if args.status not in ("Active", "Suspended", "Disabled"):
        print("Status must be Active, Suspended or Disabled.")
        return 1
    database.set_user_status(user["id"], args.status)
    database.add_audit_log("user.update", user_id=user["id"],
                           details=f"status={args.status} via manage_users CLI")
    print(f"'{user['username']}' status set to {args.status}.")
    return 0


def cmd_verify(args):
    """Check that a stored hash matches a given password (no changes)."""
    user = _get_user(args.username)
    if not user:
        return 1
    password = getpass.getpass("Password to verify (hidden): ")
    ok = check_password_hash(user["password_hash"], password)
    print("Password matches." if ok else "Password does NOT match.")
    return 0 if ok else 1


def _get_user(username):
    user = database.get_user_by_username(username.strip())
    if not user:
        print(f"No user named '{username}'.")
        return None
    return user


def _build_parser():
    p = argparse.ArgumentParser(description="Lyka Realty CRM user management")
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("create-admin", help="create a Super Admin account")
    pa.add_argument("username")
    pa.add_argument("--full-name")
    pa.add_argument("--email")
    pa.add_argument("--department")
    pa.set_defaults(func=cmd_create_admin)

    pu = sub.add_parser("create-user", help="create a staff/client account")
    pu.add_argument("username")
    pu.add_argument("--roles", nargs="+", required=True,
                    help="one or more role names, e.g. --roles 'Sales/CRM' 'Marketing'")
    pu.add_argument("--full-name")
    pu.add_argument("--email")
    pu.add_argument("--department")
    pu.add_argument("--status", default="Active",
                    choices=("Active", "Suspended", "Disabled"))
    pu.set_defaults(func=cmd_create_user)

    pl = sub.add_parser("list", help="list all accounts")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("reset-password", help="reset a user's password")
    pr.add_argument("username")
    pr.set_defaults(func=cmd_reset_password)

    ps = sub.add_parser("status", help="set Active/Suspended/Disabled")
    ps.add_argument("username")
    ps.add_argument("status", choices=("Active", "Suspended", "Disabled"))
    ps.set_defaults(func=cmd_status)

    pv = sub.add_parser("verify", help="check a password against the stored hash")
    pv.add_argument("username")
    pv.set_defaults(func=cmd_verify)

    return p


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))