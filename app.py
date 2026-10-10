"""
app.py
AI-Powered Property CRM — Flask application.

Run:
    python seed_data.py   # optional: load sample data
    python app.py

Then open http://127.0.0.1:5000 in your browser.
"""

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, Response, g,
)
import os
import uuid
from datetime import datetime

from database import (
    init_db, get_all_properties, get_property, add_property,
    update_property, delete_property, get_all_leads, get_lead,
    add_lead, update_lead, delete_lead, get_dashboard_stats,
    add_property_images, get_property_images, get_property_image,
    delete_property_image, get_location_distribution,
    get_bedroom_distribution, get_lead_status_summary,
    get_recent_properties, get_recent_leads, get_due_follow_ups,
    BUSINESS_CATEGORIES, SOURCE_TYPES, BUSINESS_STATUSES,
    REQUIREMENT_TYPES, PRIORITIES, REQUIREMENT_STATUSES, REQUIREMENT_CATEGORIES,
    get_all_business_entries, get_business_entry, add_business_entry,
    update_business_entry, delete_business_entry, get_business_summary,
    get_all_requirements, get_requirement, add_requirement,
    update_requirement, delete_requirement, get_requirement_summary,
    get_gap_analysis,
    bootstrap_roles, get_user_by_id,
)
from services.groq_service import get_ai_response
from seed_data import seed
from config import (
    SECRET_KEY, CURRENCY, APP_ENV, DEBUG, PERMANENT_SESSION_LIFETIME,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE,
    ASSISTANT_RATE_LIMIT, ASSISTANT_RATE_WINDOW_SECONDS,
)
from brd import build_brd
from services.pdf_exporter import export_brd_pdf, pdf_available
from security import (
    audit, can, csrf_token, end_session, is_client, load_user,
    login_required, permission_required, RateLimiter, validate_csrf,
)
from auth_routes import auth_bp

app = Flask(__name__)
app.secret_key = SECRET_KEY

# --- session & cookie security (from config / .env) ---
app.config["PERMANENT_SESSION_LIFETIME"] = PERMANENT_SESSION_LIFETIME
app.config["SESSION_COOKIE_HTTPONLY"] = SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE

app.register_blueprint(auth_bp)

# AI assistant rate limiter (per client IP).
assistant_limiter = RateLimiter(ASSISTANT_RATE_LIMIT, ASSISTANT_RATE_WINDOW_SECONDS)

# Display currency (stored prices are never changed). Available in every
# template as {{ CURRENCY }}.
app.jinja_env.globals["CURRENCY"] = CURRENCY

# Canonical lead sources offered by the lead form. The Source filter always
# shows these (plus any extra values already stored on leads).
LEAD_SOURCES = ("Website", "Referral", "Social Media", "Walk-in", "Other")

# --- image upload settings ---
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
UPLOAD_FOLDER = os.path.join(app.static_folder, "uploads", "properties")
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB per request
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def valid_image_signature(storage):
    """Verify the file's magic bytes match its extension.

    The extension allow-list alone is not enough — a crafted file can lie
    about its type. We read the first bytes and confirm the real format:
      PNG  : 89 50 4E 47
      JPEG : FF D8 FF
      GIF  : GIF87a / GIF89a
      WEBP : RIFF .... WEBP
    """
    try:
        head = storage.stream.read(12)
        storage.stream.seek(0)
    except OSError:
        return False
    ext = os.path.splitext(storage.filename)[1].lower()
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return head[:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def save_property_images(file_storage_list):
    """
    Save uploaded images with generated (uuid) filenames — client filenames
    are never trusted. Returns the list of filenames actually saved.
    """
    saved = []
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    for storage in file_storage_list:
        if not storage or not storage.filename:
            continue
        ext = os.path.splitext(storage.filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            flash(f"Skipped '{storage.filename}' — allowed types: JPG, PNG, GIF, WEBP.", "error")
            continue
        if not valid_image_signature(storage):
            flash(f"Skipped '{storage.filename}' — file content does not match its image type.", "error")
            continue
        filename = uuid.uuid4().hex + ext
        storage.save(os.path.join(UPLOAD_FOLDER, filename))
        saved.append(filename)
    return saved


def remove_image_file(filename):
    """Delete an uploaded file from disk (safe if already gone)."""
    try:
        path = os.path.join(UPLOAD_FOLDER, os.path.basename(filename))
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@app.errorhandler(413)
def upload_too_large(_error):
    flash("Upload too large — maximum 10 MB per request.", "error")
    return redirect(url_for("properties_page")), 303

# Create tables on startup
init_db()
bootstrap_roles()


# ---------------------- AUTH & CSRF (Phase 2) ----------------------

@app.before_request
def _before_request():
    """Enforce login + CSRF and load the current user for every request."""
    load_user()

    # Reject anonymous access to everything except static files and the
    # login page itself (defence in depth, applied globally).
    if g.get("user") is None and request.endpoint not in (
        "static", "auth.login",
    ):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Unauthenticated"}), 401
        flash("Please log in to continue.", "info")
        return redirect(url_for("auth.login", next=request.path))

    # Disabled / suspended accounts are logged out immediately.
    if g.get("user") and g.user["status"] != "Active":
        end_session()
        flash("Your account is not active. Contact an administrator.", "error")
        return redirect(url_for("auth.login"))

    # CSRF: every state-changing request must carry the session token.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not validate_csrf():
            audit("csrf.rejected", entity_type="request",
                  details=f"{request.method} {request.path}")
            if request.path.startswith("/api/"):
                return jsonify({"error": "Invalid or missing CSRF token"}), 400
            flash("Your request could not be verified (CSRF). Please try again.", "error")
            redirect_target = request.form.get("_next") or request.referrer \
                or url_for("dashboard")
            if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                return redirect(redirect_target)
            return redirect(url_for("dashboard"))


@app.context_processor
def _inject_user_and_csrf():
    """Expose the current user, role checks and CSRF token to templates."""
    def can_check(permission):
        return can(g.get("user"), permission)

    def has_role(role_name):
        from security import user_roles
        return role_name in user_roles(g.get("user"))

    return {
        "current_user": g.get("user"),
        "can": can_check,
        "has_role": has_role,
        "csrf_token": csrf_token,
    }


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template(
        "error.html", code=404, title="Page not found",
        message="The page you requested does not exist.",
    ), 404


@app.errorhandler(500)
def server_error(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return render_template(
        "error.html", code=500, title="Something went wrong",
        message="An unexpected error occurred. Please try again.",
    ), 500


# ---------------------- HOME / DASHBOARD ----------------------

@app.route("/")
def dashboard():
    if is_client(g.get("user")):
        from database import get_all_leads
        my_leads = [
            l for l in get_all_leads()
            if l.get("client_user_id") == g.user["id"]
        ]
        return render_template(
            "client_dashboard.html",
            my_leads=my_leads,
            featured=get_recent_properties(6),
            today=datetime.now().strftime("%Y-%m-%d"),
        )

    stats = get_dashboard_stats()
    location_distribution = get_location_distribution()
    bedroom_distribution = get_bedroom_distribution()
    lead_summary = get_lead_status_summary()
    properties = get_recent_properties(6)
    leads = get_recent_leads(5)
    due_follow_ups = get_due_follow_ups(6)
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "dashboard.html",
        stats=stats,
        location_distribution=location_distribution,
        bedroom_distribution=bedroom_distribution,
        lead_summary=lead_summary,
        properties=properties,
        leads=leads,
        due_follow_ups=due_follow_ups,
        today=today,
    )


# ---------------------- PROPERTIES CRUD ----------------------

@app.route("/properties")
@permission_required("properties.view")
def properties_page():
    # --- collect every filter from the query string ---
    f = {
        "q": request.args.get("q", "").strip(),
        "status": request.args.get("status", ""),
        "location": request.args.get("location", "").strip(),
        "min_price": request.args.get("min_price", "").strip(),
        "max_price": request.args.get("max_price", "").strip(),
        "bedrooms": request.args.get("bedrooms", ""),
        "bathrooms": request.args.get("bathrooms", ""),
        "pool": request.args.get("pool", ""),
        "metro": request.args.get("metro", ""),
        "view": request.args.get("view", ""),
    }

    items = get_all_properties()

    # --- existing behaviour (unchanged) ---
    if f["status"]:
        items = [p for p in items if p["status"] == f["status"]]
    if f["q"]:
        ql = f["q"].lower()
        items = [
            p for p in items
            if ql in p["name"].lower() or ql in p["location"].lower()
        ]

    # --- location (matches location only) ---
    if f["location"]:
        loc = f["location"].lower()
        items = [p for p in items if loc in (p["location"] or "").lower()]

    # --- price range (invalid input is ignored, never a 500) ---
    try:
        min_price = float(f["min_price"]) if f["min_price"] else None
    except ValueError:
        min_price = None
    try:
        max_price = float(f["max_price"]) if f["max_price"] else None
    except ValueError:
        max_price = None
    if min_price is not None:
        items = [p for p in items if p["price"] >= min_price]
    if max_price is not None:
        items = [p for p in items if p["price"] <= max_price]

    # --- bedrooms / bathrooms (exact match) ---
    if f["bedrooms"].isdigit():
        items = [p for p in items if p["bedrooms"] == int(f["bedrooms"])]
    if f["bathrooms"].isdigit():
        items = [p for p in items if p["bathrooms"] == int(f["bathrooms"])]

    # --- swimming pool / nearby metro (Yes or No, empty = any) ---
    if f["pool"] in ("Yes", "No"):
        items = [p for p in items if str(p["has_swimming_pool"]) == f["pool"]]
    if f["metro"] in ("Yes", "No"):
        items = [p for p in items if str(p["nearby_metro"]) == f["metro"]]

    # --- property view (exact match; "None" = empty view) ---
    if f["view"] == "None":
        items = [p for p in items if not (p["property_view"] or "").strip()]
    elif f["view"]:
        items = [p for p in items if (p["property_view"] or "") == f["view"]]

    return render_template(
        "properties.html",
        properties=items,
        **f,
    )


@app.route("/properties/<int:property_id>")
@permission_required("properties.view")
def property_detail_page(property_id):
    prop = get_property(property_id)
    if not prop:
        flash("Property not found.", "error")
        return redirect(url_for("properties_page"))
    images = get_property_images(property_id)
    return render_template(
        "property_detail.html", property=prop, images=images
    )


@app.route("/properties/new", methods=["GET", "POST"])
@permission_required("properties.create")
def add_property_page():
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            property_id = add_property(data)
            filenames = save_property_images(request.files.getlist("images"))
            add_property_images(property_id, filenames)
            audit("property.create", entity_type="property",
                  entity_id=property_id,
                  details=f"name={data.get('name')!r}")
            if filenames:
                flash(
                    f"Property added with {len(filenames)} photo"
                    f"{'s' if len(filenames) != 1 else ''}!",
                    "success",
                )
            else:
                flash("Property added successfully!", "success")
            return redirect(url_for("properties_page"))
        except (ValueError, TypeError):
            flash("Please fill in all required fields with valid numbers.", "error")
            return render_template(
                "property_form.html", property=None, action="add", images=[]
            )

    return render_template(
        "property_form.html", property=None, action="add", images=[]
    )


@app.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
@permission_required("properties.edit")
def edit_property_page(property_id):
    prop = get_property(property_id)
    if not prop:
        flash("Property not found.", "error")
        return redirect(url_for("properties_page"))

    if request.method == "POST":
        data = request.form.to_dict()
        try:
            update_property(property_id, data)
            filenames = save_property_images(request.files.getlist("images"))
            add_property_images(property_id, filenames)
            audit("property.update", entity_type="property",
                  entity_id=property_id,
                  details=f"name={data.get('name')!r}")
            if filenames:
                flash(
                    f"Added {len(filenames)} new photo"
                    f"{'s' if len(filenames) != 1 else ''}.",
                    "success",
                )
            else:
                flash("Property updated successfully!", "success")
            return redirect(url_for("property_detail_page", property_id=property_id))
        except (ValueError, TypeError):
            flash("Please fill in all required fields with valid numbers.", "error")
            return render_template(
                "property_form.html", property=prop, action="edit",
                images=get_property_images(property_id),
            )

    return render_template(
        "property_form.html", property=prop, action="edit",
        images=get_property_images(property_id),
    )


@app.route("/properties/<int:property_id>/delete", methods=["POST"])
@permission_required("properties.delete")
def delete_property_page(property_id):
    filenames = delete_property(property_id)
    for filename in filenames:
        remove_image_file(filename)
    audit("property.delete", entity_type="property", entity_id=property_id)
    flash("Property deleted.", "info")
    return redirect(url_for("properties_page"))


@app.route(
    "/properties/<int:property_id>/images/<int:image_id>/delete",
    methods=["POST"],
)
def delete_property_image_page(property_id, image_id):
    if not can(g.get("user"), "properties.edit"):
        return render_template(
            "error.html", code=403, title="Access denied",
            message="You do not have permission to modify property images.",
        ), 403
    image = get_property_image(image_id)
    if image and image["property_id"] == property_id:
        delete_property_image(image_id)
        remove_image_file(image["filename"])
        flash("Photo deleted.", "info")
    else:
        flash("Photo not found.", "error")
    return redirect(url_for("edit_property_page", property_id=property_id))


# ---------------------- LEADS / CLIENTS CRUD ----------------------

@app.route("/leads")
@permission_required("leads.view")
def leads_page():
    status = request.args.get("status", "")
    q = request.args.get("q", "")
    source = request.args.get("source", "")
    follow_up = request.args.get("follow_up", "")
    min_score = request.args.get("min_score", "")
    min_budget = request.args.get("min_budget", "")
    max_budget = request.args.get("max_budget", "")
    items = get_all_leads()
    today = datetime.now().strftime("%Y-%m-%d")

    # Clients see ONLY their own authorised records (row-level isolation).
    if is_client(g.get("user")):
        items = [l for l in items if l.get("client_user_id") == g.user["id"]]

    if status:
        items = [l for l in items if l["status"] == status]
    if q:
        ql = q.lower()
        items = [
            l for l in items
            if ql in l["client_name"].lower() or ql in (l["email"] or "").lower()
            or ql in (l["phone"] or "")
        ]

    if source:
        items = [l for l in items if (l.get("lead_source") or "") == source]

    if follow_up:
        def follow_up_state(date_str):
            if not date_str:
                return "none"
            if date_str < today:
                return "overdue"
            if date_str == today:
                return "today"
            return "upcoming"
        items = [
            l for l in items if follow_up_state(l.get("next_follow_up")) == follow_up
        ]

    if min_score:
        try:
            min_score_val = int(min_score)
        except ValueError:
            min_score_val = None
        if min_score_val is not None:
            items = [l for l in items if (l.get("lead_score") or 0) >= min_score_val]

    try:
        min_budget_val = float(min_budget) if min_budget else None
    except ValueError:
        min_budget_val = None
    try:
        max_budget_val = float(max_budget) if max_budget else None
    except ValueError:
        max_budget_val = None
    if min_budget_val is not None:
        items = [l for l in items if l.get("budget") is not None and l["budget"] >= min_budget_val]
    if max_budget_val is not None:
        items = [l for l in items if l.get("budget") is not None and l["budget"] <= max_budget_val]

    used_sources = {
        (l.get("lead_source") or "").strip() for l in items
        if (l.get("lead_source") or "").strip()
    }
    sources = list(LEAD_SOURCES) + sorted(used_sources - set(LEAD_SOURCES))

    return render_template(
        "leads.html",
        leads=items,
        status=status,
        q=q,
        source=source,
        follow_up=follow_up,
        min_score=min_score,
        min_budget=min_budget,
        max_budget=max_budget,
        sources=sources,
        today=today,
    )


@app.route("/leads/new", methods=["GET", "POST"])
@permission_required("leads.create")
def add_lead_page():
    if request.method == "POST":
        data = request.form.to_dict()
        # A Sales user automatically owns the lead they create; a Marketing
        # lead stays unassigned for later sales assignment.
        if g.get("user") and can(g.get("user"), "leads.edit_own"):
            data["owner_user_id"] = g.user["id"]
        try:
            lead_id = add_lead(data)
            audit("lead.create", entity_type="lead", entity_id=lead_id,
                  details=f"client={data.get('client_name')!r}")
            flash("Lead added successfully!", "success")
            return redirect(url_for("leads_page"))
        except (ValueError, TypeError):
            flash("Please fill in the client name correctly.", "error")
            return render_template("lead_form.html", lead=None, action="add")

    return render_template("lead_form.html", lead=None, action="add")


def _can_edit_lead(lead):
    """True when the current user may edit/update a lead.

    Admins (leads.edit) edit any lead; Sales (leads.edit_own) may only edit
    leads they own or leads with no owner yet; everyone else is denied.
    """
    user = g.get("user")
    if not user:
        return False
    if can(user, "leads.edit"):
        return True
    if can(user, "leads.edit_own"):
        return (lead.get("owner_user_id") is None
                or lead["owner_user_id"] == user["id"])
    return False


@app.route("/leads/<int:lead_id>/edit", methods=["GET", "POST"])
def edit_lead_page(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("leads_page"))
    if not _can_edit_lead(lead):
        return render_template(
            "error.html", code=403, title="Access denied",
            message="You cannot edit this lead.",
        ), 403

    if request.method == "POST":
        data = request.form.to_dict()
        try:
            update_lead(lead_id, data)
            audit("lead.update", entity_type="lead", entity_id=lead_id,
                  details=f"client={data.get('client_name')!r}")
            flash("Lead updated successfully!", "success")
            return redirect(url_for("leads_page"))
        except (ValueError, TypeError):
            flash("Please fill in the client name correctly.", "error")
            return render_template("lead_form.html", lead=lead, action="edit")

    return render_template("lead_form.html", lead=lead, action="edit")


@app.route("/leads/<int:lead_id>/delete", methods=["POST"])
@permission_required("leads.delete")
def delete_lead_page(lead_id):
    delete_lead(lead_id)
    audit("lead.delete", entity_type="lead", entity_id=lead_id)
    flash("Lead deleted.", "info")
    return redirect(url_for("leads_page"))


@app.route("/leads/<int:lead_id>/status", methods=["POST"])
def update_lead_status_page(lead_id):
    """Inline quick-status dropdown — reuses the normal update_lead() logic.

    Only the five real pipeline statuses are accepted, so no invalid stage
    can ever be written. The score is recomputed from the full lead again.

    Status changes are consequential: limited to users who may edit the
    lead, and every change is written to the audit log.
    """
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("leads_page"))
    if not _can_edit_lead(lead):
        return render_template(
            "error.html", code=403, title="Access denied",
            message="You cannot change this lead's status.",
        ), 403

    new_status = request.form.get("status", "")
    if new_status in ("New", "Contacted", "Qualified", "Closed", "Lost"):
        old_status = lead["status"]
        lead["status"] = new_status
        update_lead(lead_id, lead)
        audit("lead.status_change", entity_type="lead", entity_id=lead_id,
              details=f"{old_status!r} -> {new_status!r}")
        flash(f"{lead['client_name']} moved to {new_status}.", "info")
    else:
        flash("Invalid status — nothing changed.", "error")

    return redirect(url_for("leads_page"))


# ---------------------- AI ASSISTANT ----------------------

@app.route("/assistant")
@permission_required("assistant.use")
def assistant_page():
    return render_template("assistant.html")


@app.route("/api/assistant", methods=["POST"])
def assistant_api():
    if not can(g.get("user"), "assistant.use"):
        return jsonify({"error": "Forbidden"}), 403

    client_ip = request.remote_addr or "unknown"
    if not assistant_limiter.allow(client_ip):
        return jsonify({
            "error": "Too many requests",
            "reply": "Please wait a moment before asking again.",
        }), 429

    try:
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()

        if not message:
            return jsonify({"reply": "Please enter a message."})

        reply = get_ai_response(message)

        return jsonify({"reply": reply})

    except Exception:
        # Never leak internal error details to the browser. The server log
        # still records the real cause via the standard exception hook.
        import traceback
        traceback.print_exc()
        return jsonify({
            "reply": "Sorry, I ran into an internal error. Please try again.",
        })


# ---------------------- BUSINESS ANALYSIS (Phase 3) ----------------------

@app.route("/business")
@permission_required("planning.view")
def business_page():
    category = request.args.get("category", "").strip()
    source_type = request.args.get("source_type", "").strip()
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    entries = get_all_business_entries(category, source_type, status, q)
    summary = get_business_summary()
    return render_template(
        "business_analysis.html",
        entries=entries,
        summary=summary,
        category=category,
        source_type=source_type,
        status=status,
        q=q,
        categories=BUSINESS_CATEGORIES,
        source_types=SOURCE_TYPES,
        statuses=BUSINESS_STATUSES,
    )


@app.route("/business/new", methods=["GET", "POST"])
@permission_required("planning.edit")
def add_business_page():
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            entry_id = add_business_entry(data)
            audit("business.create", entity_type="business", entity_id=entry_id,
                  details=f"title={data.get('title')!r}")
            flash("Business note added!", "success")
            return redirect(url_for("business_page"))
        except ValueError:
            flash("Please fill in a title.", "error")
            return render_template(
                "business_analysis_form.html", entry=None, action="add",
                categories=BUSINESS_CATEGORIES,
                source_types=SOURCE_TYPES,
                statuses=BUSINESS_STATUSES,
            )

    return render_template(
        "business_analysis_form.html", entry=None, action="add",
        categories=BUSINESS_CATEGORIES,
        source_types=SOURCE_TYPES,
        statuses=BUSINESS_STATUSES,
    )


@app.route("/business/<int:entry_id>/edit", methods=["GET", "POST"])
@permission_required("planning.edit")
def edit_business_page(entry_id):
    entry = get_business_entry(entry_id)
    if not entry:
        flash("Business note not found.", "error")
        return redirect(url_for("business_page"))

    if request.method == "POST":
        data = request.form.to_dict()
        try:
            update_business_entry(entry_id, data)
            audit("business.update", entity_type="business", entity_id=entry_id,
                  details=f"title={data.get('title')!r}")
            flash("Business note updated!", "success")
            return redirect(url_for("business_page"))
        except ValueError:
            flash("Please fill in a title.", "error")
            return render_template(
                "business_analysis_form.html", entry=entry, action="edit",
                categories=BUSINESS_CATEGORIES,
                source_types=SOURCE_TYPES,
                statuses=BUSINESS_STATUSES,
            )

    return render_template(
        "business_analysis_form.html", entry=entry, action="edit",
        categories=BUSINESS_CATEGORIES,
        source_types=SOURCE_TYPES,
        statuses=BUSINESS_STATUSES,
    )


@app.route("/business/<int:entry_id>/delete", methods=["POST"])
@permission_required("planning.edit")
def delete_business_page(entry_id):
    delete_business_entry(entry_id)
    audit("business.delete", entity_type="business", entity_id=entry_id)
    flash("Business note deleted.", "info")
    return redirect(url_for("business_page"))


# ---------------------- REQUIREMENTS & GAP ANALYSIS (Phase 3) ----------------------

@app.route("/requirements")
@permission_required("planning.view")
def requirements_page():
    req_type = request.args.get("req_type", "").strip()
    priority = request.args.get("priority", "").strip()
    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    q = request.args.get("q", "").strip()
    items = get_all_requirements(req_type, priority, status, category, q)
    summary = get_requirement_summary()
    return render_template(
        "requirements.html",
        items=items,
        summary=summary,
        req_type=req_type,
        priority=priority,
        status=status,
        category=category,
        q=q,
        req_types=REQUIREMENT_TYPES,
        priorities=PRIORITIES,
        statuses=REQUIREMENT_STATUSES,
        categories=REQUIREMENT_CATEGORIES,
    )


@app.route("/requirements/new", methods=["GET", "POST"])
@permission_required("planning.edit")
def add_requirement_page():
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            req_id = add_requirement(data)
            audit("requirement.create", entity_type="requirement",
                  entity_id=req_id,
                  details=f"title={data.get('title')!r}")
            flash("Requirement added!", "success")
            return redirect(url_for("requirements_page"))
        except ValueError:
            flash("Please fill in a title.", "error")
            return render_template(
                "requirements_form.html", req=None, action="add",
                req_types=REQUIREMENT_TYPES,
                priorities=PRIORITIES,
                statuses=REQUIREMENT_STATUSES,
                categories=REQUIREMENT_CATEGORIES,
            )

    return render_template(
        "requirements_form.html", req=None, action="add",
        req_types=REQUIREMENT_TYPES,
        priorities=PRIORITIES,
        statuses=REQUIREMENT_STATUSES,
        categories=REQUIREMENT_CATEGORIES,
    )


@app.route("/requirements/<int:req_id>/edit", methods=["GET", "POST"])
@permission_required("planning.edit")
def edit_requirement_page(req_id):
    req = get_requirement(req_id)
    if not req:
        flash("Requirement not found.", "error")
        return redirect(url_for("requirements_page"))

    if request.method == "POST":
        data = request.form.to_dict()
        try:
            update_requirement(req_id, data)
            audit("requirement.update", entity_type="requirement",
                  entity_id=req_id,
                  details=f"title={data.get('title')!r}")
            flash("Requirement updated!", "success")
            return redirect(url_for("requirements_page"))
        except ValueError:
            flash("Please fill in a title.", "error")
            return render_template(
                "requirements_form.html", req=req, action="edit",
                req_types=REQUIREMENT_TYPES,
                priorities=PRIORITIES,
                statuses=REQUIREMENT_STATUSES,
                categories=REQUIREMENT_CATEGORIES,
            )

    return render_template(
        "requirements_form.html", req=req, action="edit",
        req_types=REQUIREMENT_TYPES,
        priorities=PRIORITIES,
        statuses=REQUIREMENT_STATUSES,
        categories=REQUIREMENT_CATEGORIES,
    )


@app.route("/requirements/<int:req_id>/delete", methods=["POST"])
@permission_required("planning.edit")
def delete_requirement_page(req_id):
    delete_requirement(req_id)
    audit("requirement.delete", entity_type="requirement", entity_id=req_id)
    flash("Requirement deleted.", "info")
    return redirect(url_for("requirements_page"))


@app.route("/gap-analysis")
@permission_required("planning.view")
def gap_analysis_page():
    view = get_gap_analysis()
    summary = get_requirement_summary()
    only_gaps = request.args.get("only_gaps", "") == "1"
    req_type = request.args.get("req_type", "").strip()
    priority = request.args.get("priority", "").strip()
    status = request.args.get("status", "").strip()

    items = view["items"]
    if only_gaps:
        items = [i for i in items if i["has_gap"]]
    if req_type:
        items = [i for i in items if i["req_type"] == req_type]
    if priority:
        items = [i for i in items if i["priority"] == priority]
    if status:
        items = [i for i in items if i["status"] == status]

    return render_template(
        "gap_analysis.html",
        items=items,
        view=view,
        summary=summary,
        only_gaps=only_gaps,
        req_type=req_type,
        priority=priority,
        status=status,
        req_types=REQUIREMENT_TYPES,
        priorities=PRIORITIES,
        statuses=REQUIREMENT_STATUSES,
    )


# ---------------------- BRD GENERATOR (Phase 4) ----------------------

@app.route("/brd")
@permission_required("planning.view")
def brd_page():
    """Live preview of the Business Requirements Document."""
    doc = build_brd()
    return render_template(
        "brd.html",
        doc=doc,
        pdf_available=pdf_available(),
    )


@app.route("/brd/export")
@permission_required("planning.view")
def brd_export():
    """Download the BRD as a PDF (requires the fpdf2 library)."""
    if not pdf_available():
        flash(
            "PDF export is not available because the 'fpdf2' library is not "
            "installed. Install it with: pip install fpdf2",
            "error",
        )
        return redirect(url_for("brd_page"))

    doc = build_brd()
    pdf_bytes = export_brd_pdf(doc)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"BRD_LykaRealty_{stamp}.pdf"
    response = Response(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Length"] = str(len(pdf_bytes))
    return response


# ---------------------- RUN ----------------------

if __name__ == "__main__":
    seed()
    # Debug is controlled by config (DEBUG=1, never in production).
    print(f"Lyka Realty CRM — environment={APP_ENV} debug={DEBUG}")
    app.run(debug=DEBUG, port=5000)
