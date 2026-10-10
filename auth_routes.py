"""
auth_routes.py
Phase 2 — login, logout and admin user/role management routes.

Only a user with the 'users.manage' permission (Super Admin) can create or
modify accounts. There is intentionally NO public self-registration.

Passwords are stored hashed (werkzeug). Sessions are rebuilt on login as a
defence against session fixation.
"""

import sqlite3

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    create_user, get_user_by_id, get_user_by_username, get_user_roles,
    list_users, role_names, set_user_password, set_user_roles, set_user_status,
    update_last_login, update_user,
)
from security import (
    ROLE_SUPER_ADMIN,
    audit, can, end_session, establish_session, permission_required,
)

auth_bp = Blueprint("auth", __name__)

VALID_STATUSES = ("Active", "Suspended", "Disabled")
MIN_PASSWORD_LENGTH = 8


def _next_target():
    """Safe post-login target: only same-site relative paths (no open redirect)."""
    target = (request.args.get("next") or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("dashboard")


# --------------------------------------------------------------------------- #
# Login / logout
# --------------------------------------------------------------------------- #

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = get_user_by_username(username)
        bad_login = True
        if user and check_password_hash(user["password_hash"], password):
            if user["status"] != "Active":
                audit("auth.login_blocked", entity_type="user",
                      entity_id=user["id"], details="account not Active")
                flash(
                    "This account is not active. Contact an administrator.",
                    "error",
                )
                return render_template("login.html", username=username)
            establish_session(user["id"])
            update_last_login(user["id"])
            audit("auth.login", entity_type="user", entity_id=user["id"])
            return redirect(_next_target())

        audit("auth.login_failed", entity_type="user",
              details=f"username={username!r}" if username else "no username")
        flash("Invalid username or password.", "error")
        return render_template("login.html", username=username), 401

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    user_id = getattr(g, "user", None) and g.user.get("id")
    end_session()
    if user_id:
        audit("auth.logout", entity_type="user", entity_id=user_id)
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# --------------------------------------------------------------------------- #
# User administration (Super Admin)
# --------------------------------------------------------------------------- #

@auth_bp.route("/admin/users")
@permission_required("users.manage")
def users_list():
    users = list_users()
    roles_by_user = {u["id"]: get_user_roles(u["id"]) for u in users}
    return render_template(
        "users.html",
        users=users,
        roles_by_user=roles_by_user,
        valid_statuses=VALID_STATUSES,
    )


@auth_bp.route("/admin/users/new", methods=["GET", "POST"])
@permission_required("users.manage")
def users_new():
    available_roles = role_names()
    if request.method == "POST":
        form = request.form
        username = (form.get("username") or "").strip()
        password = form.get("password") or ""
        selected_roles = [r for r in form.getlist("roles") if r in available_roles]

        error = None
        if not username:
            error = "Username is required."
        elif not password:
            error = "Password is required."
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        elif not selected_roles:
            error = "Choose at least one role."
        elif get_user_by_username(username):
            error = f"Username '{username}' is already taken."

        if error:
            flash(error, "error")
            return render_template(
                "user_form.html", user=None, available_roles=available_roles,
                valid_statuses=VALID_STATUSES, form=form,
            )

        try:
            user_id = create_user(
                username=username,
                password_hash=generate_password_hash(password),
                full_name=form.get("full_name"),
                email=form.get("email"),
                department=form.get("department"),
                roles=selected_roles,
                status=form.get("status") or "Active",
            )
        except sqlite3.IntegrityError:
            flash("A user with that username or email already exists.", "error")
            return render_template(
                "user_form.html", user=None, available_roles=available_roles,
                valid_statuses=VALID_STATUSES, form=form,
            )

        audit("user.create", entity_type="user", entity_id=user_id,
              details=f"roles={selected_roles}")
        flash(f"User '{username}' created.", "success")
        return redirect(url_for("auth.users_list"))

    return render_template(
        "user_form.html", user=None, available_roles=available_roles,
        valid_statuses=VALID_STATUSES,
    )


@auth_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@permission_required("users.manage")
def users_edit(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("auth.users_list"))

    available_roles = role_names()
    current_roles = get_user_roles(user_id)
    current = g.user
    is_self = current and current["id"] == user_id

    if request.method == "POST":
        form = request.form
        selected_roles = [r for r in form.getlist("roles") if r in available_roles]
        new_status = form.get("status") or "Active"
        new_password = form.get("password") or ""

        # Protection against self-lockouts.
        if is_self and new_status != "Active":
            flash("You cannot disable your own account.", "error")
            new_status = user["status"]
        if (is_self and ROLE_SUPER_ADMIN in current_roles
                and new_status == "Active" and ROLE_SUPER_ADMIN not in selected_roles):
            flash("You cannot remove your own Super Admin role.", "error")
            selected_roles = current_roles

        if new_password:
            if len(new_password) < MIN_PASSWORD_LENGTH:
                flash(
                    f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
                    "error",
                )
                return redirect(url_for("auth.users_edit", user_id=user_id))
            set_user_password(user_id, generate_password_hash(new_password))
            audit("user.password_reset", entity_type="user", entity_id=user_id)

        update_user(user_id, full_name=form.get("full_name"),
                    email=form.get("email"), department=form.get("department"),
                    status=new_status)
        if selected_roles != sorted(current_roles):
            set_user_roles(user_id, selected_roles)
        set_user_status(user_id, new_status)

        audit("user.update", entity_type="user", entity_id=user_id,
              details=f"status={new_status} roles={sorted(selected_roles)}")
        flash("User updated.", "success")
        return redirect(url_for("auth.users_list"))

    return render_template(
        "user_form.html", user=user, available_roles=available_roles,
        valid_statuses=VALID_STATUSES, current_roles=current_roles,
    )


# --------------------------------------------------------------------------- #
# Audit log (Super Admin / Company Admin)
# --------------------------------------------------------------------------- #

@auth_bp.route("/admin/audit")
@permission_required("audit.view")
def audit_list():
    return render_template(
        "audit_log.html",
        logs=audit_logs_safe(),
    )


def audit_logs_safe(limit=200):
    from database import get_audit_logs
    return get_audit_logs(limit) if can(g.get("user"), "audit.view") else []