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
    LEAD_STATUSES, LEGACY_LEAD_STATUSES, ALL_LEAD_STATUSES,
    add_lead_note, get_lead_notes, get_lead_status_history,
    save_recommendations, get_lead_recommendations,
    get_latest_recommendations, get_recent_recommendations,
)
from services.groq_service import get_ai_response
from services.ai_extract import analyse_enquiry, AiProviderError, provider_status
from services.lead_schema import EnquiryValidationError
from services.matching import match_properties, MATCH_WEIGHTS, ENGINE_VERSION
from seed_data import seed
from config import (
    SECRET_KEY, CURRENCY, APP_ENV, DEBUG, PERMANENT_SESSION_LIFETIME,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE,
    ASSISTANT_RATE_LIMIT, ASSISTANT_RATE_WINDOW_SECONDS,
    AI_ANALYSIS_RATE_LIMIT, AI_ANALYSIS_RATE_WINDOW,
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

# Lead-analysis rate limiter (per client IP) — AI calls are expensive.
analysis_limiter = RateLimiter(AI_ANALYSIS_RATE_LIMIT, AI_ANALYSIS_RATE_WINDOW)

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
    recent_recommendations = get_recent_recommendations(5)
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
        recent_recommendations=recent_recommendations,
        today=today,
    )


# ---------------------- PROPERTIES CRUD ----------------------

# Free-text `property_type` column: offer these alongside whatever distinct
# values already exist in the data.
_STANDARD_PROPERTY_TYPES = {
    "Apartment", "Villa", "Penthouse", "Townhouse", "Studio", "Office", "Land",
}

# Communities used only for the decorative card image labels.
_PRIME_COMMUNITIES = {
    "palm jumeirah", "jumeirah beach residence", "dubai harbour",
    "umm suqeim", "jumeirah", "difc",
}
_POPULAR_COMMUNITIES = {
    "downtown dubai", "dubai marina", "jumeirah village circle",
}


def _percentile(values, pct):
    """Value at pct (0-1) of a sorted list; None when there is no data."""
    if not values:
        return None
    ordered = sorted(values)
    idx = int(len(ordered) * pct)
    return ordered[min(max(idx, 0), len(ordered) - 1)]


def _size_sqm(prop):
    """Card size: the real `property_size` column, else the legacy
    "Size: NNN sqm" string the historical import stored in `property_view`.
    Returns None when no size is available."""
    raw = prop.get("property_size")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    text = prop.get("property_view") or ""
    if text.startswith("Size:"):
        num = text.split(":", 1)[1].replace("sqm", "").strip()
        try:
            return float(num)
        except ValueError:
            return None
    return None


def _image_scene(prop):
    """Pick a photographic scene category for a listing.

    Photos are matched to the *style* of the property (its name keywords and
    community), never titled as if they showed that exact unit — the database
    holds no photos, so these are representative local images only.
    """
    name = (prop.get("name") or "").lower()
    loc = (prop.get("location") or "").strip().lower()
    if "penthouse" in name or "duplex" in name:
        return "penthouse"
    if "apartment" in name or "flat" in name or "studio" in name or "tower" in name:
        return "dubai-apartment"
    if "villa" in name or "mansion" in name or "bungalow" in name:
        return "villa-pool"
    if loc in {"palm jumeirah", "jumeirah beach residence", "dubai harbour",
               "umm suqeim", "jumeirah"}:
        return "beachfront"
    if loc in {"downtown dubai", "difc", "business bay"}:
        return "skyline"
    if loc in {"dubai marina", "jumeirah lake towers",
               "dubai creek harbour (the lagoons)", "dubai water canal"}:
        return "marina"
    return "family-home"


def _image_file(prop):
    """Local 16:9 photo filename for a card.

    Two photographic variants exist per scene; they are spread deterministically
    across the listing grid by its stable id, so browsers cache only the few
    local files while the grid still looks varied.
    """
    scene = _image_scene(prop)
    variant = "b" if prop["id"] % 2 else "a"
    return f"{scene}-{variant}.jpg"


def _highlight_label(prop, price_p15, price_p85, new_from):
    """Decorative image badge, derived from real fields only."""
    if prop["id"] >= new_from:
        return "New"
    price = prop.get("price") or 0
    if price_p85 is not None and price >= price_p85:
        return "Exclusive"
    if price_p15 is not None and price <= price_p15:
        return "Best Value"
    loc = (prop.get("location") or "").strip().lower()
    if loc in _PRIME_COMMUNITIES:
        return "Featured"
    if loc in _POPULAR_COMMUNITIES:
        return "Popular"
    return ""


def _listing_purpose_display(value):
    """Map a stored listing_purpose to (css_kind, human label).

    'Sale'/'Rent' are recognised case-insensitively. Anything else — NULL,
    empty, or an unrecognised legacy value — is reported as Unknown rather
    than guessed into Sale or Rent.
    """
    purpose = str(value or "").strip().lower()
    if purpose == "rent":
        return "rent", "For Rent"
    if purpose == "sale":
        return "sale", "For Sale"
    return "unknown", "Unknown"


def _annotate_listing_cards(items):
    """Attach display-only fields used by the Properties grid.

    Nothing here is persisted: sizes, badge labels and thresholds are derived
    from existing columns so real property records are never overwritten.
    """
    prices = [p.get("price") or 0 for p in items]
    price_p15 = _percentile(prices, 0.15)
    price_p85 = _percentile(prices, 0.85)
    max_id = max((p["id"] for p in items), default=0)
    min_id = min((p["id"] for p in items), default=0)
    new_from = min_id + int((max_id - min_id + 1) * 0.95)

    for p in items:
        p["size_sqm"] = _size_sqm(p)
        p["highlight"] = _highlight_label(p, price_p15, price_p85, new_from)
        # The deal label reflects the stored listing_purpose, never the
        # availability status (a Rent listing is usually still "Available").
        # An unknown/missing purpose is left unlabelled rather than guessed.
        p["listing_kind"], p["listing_label"] = _listing_purpose_display(
            p.get("listing_purpose")
        )
        p["image_file"] = _image_file(p)


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
        "type": request.args.get("type", ""),
    }

    items = get_all_properties()

    # --- card display data (derived only; never written back to the DB) ---
    _annotate_listing_cards(items)

    # --- property type (distinct values found + standard options) ---
    property_types = sorted(
        { (p.get("property_type") or "").strip()
          for p in items if (p.get("property_type") or "").strip() }
        | _STANDARD_PROPERTY_TYPES,
        key=str.lower,
    )

    # --- existing behaviour (unchanged) ---
    if f["status"]:
        items = [p for p in items if p["status"] == f["status"]]
    if f["q"]:
        ql = f["q"].lower()
        items = [
            p for p in items
            if ql in p["name"].lower() or ql in p["location"].lower()
        ]

    # --- property type (case-insensitive exact match on the real column) ---
    if f["type"]:
        wanted = f["type"].strip().lower()
        items = [
            p for p in items
            if (p.get("property_type") or "").strip().lower() == wanted
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
        property_types=property_types,
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
    listing_kind, listing_label = _listing_purpose_display(
        prop.get("listing_purpose")
    )
    return render_template(
        "property_detail.html", property=prop, images=images,
        listing_kind=listing_kind, listing_label=listing_label,
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
    priority = request.args.get("priority", "")
    lead_type = request.args.get("lead_type", "")
    assigned = request.args.get("assigned", "")
    items = get_all_leads()
    today = datetime.now().strftime("%Y-%m-%d")

    # Clients see ONLY their own authorised records (row-level isolation).
    if is_client(g.get("user")):
        items = [l for l in items if l.get("client_user_id") == g.user["id"]]

    # Filter option lists come from the full (visibility-scoped) set.
    base_items = items
    lead_type_options = sorted({
        (l.get("lead_type") or "") for l in base_items if (l.get("lead_type") or "")
    })
    assigned_options = sorted({
        (l.get("assigned_to") or "") for l in base_items if (l.get("assigned_to") or "")
    })

    if status:
        items = [l for l in items if l["status"] == status]
    if priority:
        items = [l for l in items if (l.get("priority") or "") == priority]
    if lead_type:
        items = [l for l in items if (l.get("lead_type") or "") == lead_type]
    if assigned:
        items = [l for l in items if (l.get("assigned_to") or "") == assigned]
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
        priority=priority,
        lead_type=lead_type,
        assigned=assigned,
        sources=sources,
        statuses=LEAD_STATUSES,
        legacy_statuses=LEGACY_LEAD_STATUSES,
        lead_type_options=lead_type_options,
        assigned_options=assigned_options,
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
            return render_template("lead_form.html", lead=None, action="add",
                                   statuses=LEAD_STATUSES, legacy_statuses=LEGACY_LEAD_STATUSES)

    return render_template("lead_form.html", lead=None, action="add",
                           statuses=LEAD_STATUSES, legacy_statuses=LEGACY_LEAD_STATUSES)


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
            return render_template("lead_form.html", lead=lead, action="edit",
                                   statuses=LEAD_STATUSES, legacy_statuses=LEGACY_LEAD_STATUSES)

    return render_template("lead_form.html", lead=lead, action="edit",
                           statuses=LEAD_STATUSES, legacy_statuses=LEGACY_LEAD_STATUSES)


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
    if new_status in ALL_LEAD_STATUSES:
        old_status = lead["status"]
        lead["status"] = new_status
        update_lead(lead_id, lead)
        audit("lead.status_change", entity_type="lead", entity_id=lead_id,
              details=f"{old_status!r} -> {new_status!r}")
        flash(f"{lead['client_name']} moved to {new_status}.", "info")
    else:
        flash("Invalid status — nothing changed.", "error")

    return redirect(url_for("leads_page"))


# ---------------------- LEAD ANALYSIS / DETAIL / RECOMMENDATIONS ----------------------

def _can_view_lead(lead):
    """Row-level visibility: clients see only their own linked leads."""
    user = g.get("user")
    if not user:
        return False
    if is_client(user):
        return lead.get("client_user_id") == user["id"]
    return can(user, "leads.view")


def _analysis_to_lead_data(fields, enquiry, provider, missing):
    """Map one validated extraction onto a lead row (never invents values).

    A field the customer did not state stays empty; the client name falls back
    to a clearly-marked placeholder so the NOT NULL column is satisfied without
    fabricating a person.
    """
    return {
        "client_name": fields.get("customer_name") or "Unnamed enquiry",
        "phone": fields.get("phone") or "",
        "email": fields.get("email") or "",
        "budget": (fields.get("budget_max") if fields.get("budget_max") is not None
                   else fields.get("budget_min")),
        "preferred_location": fields.get("preferred_location") or "",
        "bedrooms_needed": fields.get("bedrooms"),
        "bathrooms_needed": fields.get("bathrooms"),
        "budget_min": fields.get("budget_min"),
        "budget_max": fields.get("budget_max"),
        "currency": fields.get("currency") or CURRENCY,
        "purpose": fields.get("purpose"),
        "lead_type": fields.get("lead_type"),
        "property_type": fields.get("property_type"),
        "amenities": ", ".join(fields.get("amenities") or []),
        "timeline_days": fields.get("timeline_days"),
        "timeline_label": fields.get("timeline_label"),
        "missing_fields": ", ".join(missing or []),
        "raw_enquiry": enquiry,
        "analysis_provider": provider,
        "analysed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "Analysed",
        "lead_source": "AI Analysis",
        "notes": fields.get("other_preferences") or "",
    }


@app.route("/leads/analyse", methods=["GET", "POST"])
@permission_required("leads.create")
def analyse_lead_page():
    """Screen 2 — paste an enquiry and let the AI extract the requirements."""
    if request.method == "GET":
        return render_template(
            "lead_analysis.html", result=None, enquiry="",
            form_data=None, provider_status=provider_status(),
        )

    enquiry = request.form.get("enquiry", "")
    provider = request.form.get("provider", "").strip() or None

    if not analysis_limiter.allow(request.remote_addr or "unknown"):
        flash("Too many analyses in a short time. Please wait a moment.", "error")
        return render_template(
            "lead_analysis.html", result=None, enquiry=enquiry,
            form_data=None, provider_status=provider_status(),
        ), 429

    try:
        result = analyse_enquiry(enquiry, provider=provider)
    except EnquiryValidationError as exc:
        flash(str(exc), "error")
        return render_template(
            "lead_analysis.html", result=None, enquiry=enquiry,
            form_data=None, provider_status=provider_status(),
        )
    except AiProviderError:
        flash("The analysis service is unavailable right now. Please try again.", "error")
        return render_template(
            "lead_analysis.html", result=None, enquiry=enquiry,
            form_data=None, provider_status=provider_status(),
        )

    audit("lead.analyse", entity_type="lead",
          details=f"provider={result['provider']} degraded={result['degraded']}")
    form_data = _analysis_to_lead_data(
        result["fields"], enquiry, result["provider"], result["missing_fields"],
    )
    return render_template(
        "lead_analysis.html", result=result, enquiry=enquiry,
        form_data=form_data, provider_status=provider_status(),
    )


@app.route("/leads/analyse/save", methods=["POST"])
@permission_required("leads.create")
def save_analysed_lead_page():
    """Persist the (agent-reviewed) extraction as a real lead."""
    data = request.form.to_dict()
    if g.get("user") and can(g.get("user"), "leads.edit_own"):
        data["owner_user_id"] = g.user["id"]
    if not (data.get("client_name") or "").strip():
        data["client_name"] = "Unnamed enquiry"
    try:
        lead_id = add_lead(data)
    except (ValueError, TypeError):
        flash("Could not save the analysed lead — please review the fields.", "error")
        return redirect(url_for("analyse_lead_page"))
    audit("lead.create", entity_type="lead", entity_id=lead_id,
          details=f"source=AI analysis client={data.get('client_name')!r}")
    flash("Analysed lead saved. You can now find property matches.", "success")
    return redirect(url_for("lead_detail_page", lead_id=lead_id))


@app.route("/leads/<int:lead_id>")
@permission_required("leads.view")
def lead_detail_page(lead_id):
    """Screen 3 — full lead view: requirements, score, notes, history, matches."""
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("leads_page"))
    if not _can_view_lead(lead):
        return render_template(
            "error.html", code=403, title="Access denied",
            message="You cannot view this lead.",
        ), 403

    return render_template(
        "lead_detail.html",
        lead=lead,
        notes=get_lead_notes(lead_id),
        history=get_lead_status_history(lead_id),
        recommendations=get_latest_recommendations(lead_id),
        can_edit=_can_edit_lead(lead),
        statuses=LEAD_STATUSES,
        legacy_statuses=LEGACY_LEAD_STATUSES,
        today=datetime.now().strftime("%Y-%m-%d"),
    )


@app.route("/leads/<int:lead_id>/notes", methods=["POST"])
@permission_required("leads.view")
def add_lead_note_page(lead_id):
    """Append a timestamped follow-up note (PRD §G)."""
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("leads_page"))
    if not _can_edit_lead(lead):
        return render_template(
            "error.html", code=403, title="Access denied",
            message="You cannot add notes to this lead.",
        ), 403

    try:
        author = g.user["full_name"] or g.user["username"] if g.get("user") else None
        add_lead_note(lead_id, request.form.get("body", ""), author=author)
        audit("lead.note", entity_type="lead", entity_id=lead_id)
        flash("Note added.", "success")
    except ValueError:
        flash("The note cannot be empty.", "error")
    return redirect(url_for("lead_detail_page", lead_id=lead_id))


def _generate_recommendations(lead, limit=3):
    """Score every available property and persist the best matches."""
    outcome = match_properties(lead, get_all_properties(), limit=limit)
    if outcome["results"]:
        save_recommendations(
            lead["id"], outcome["results"], engine_version=outcome["engine"],
        )
    return outcome


@app.route("/leads/<int:lead_id>/recommendations", methods=["GET", "POST"])
@permission_required("leads.view")
def lead_recommendations_page(lead_id):
    """Screen 4 — generate and review property recommendations for a lead."""
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("leads_page"))
    if not _can_view_lead(lead):
        return render_template(
            "error.html", code=403, title="Access denied",
            message="You cannot view matches for this lead.",
        ), 403

    outcome = None
    if request.method == "POST":
        outcome = _generate_recommendations(lead)
        audit("lead.match", entity_type="lead", entity_id=lead_id,
              details=f"results={len(outcome['results'])}")
        if outcome["results"]:
            flash(outcome["message"], "success")
        else:
            flash(outcome["message"], "info")

    return render_template(
        "recommendations.html",
        lead=lead,
        outcome=outcome,
        latest=get_latest_recommendations(lead_id),
        history=get_lead_recommendations(lead_id),
        weights=MATCH_WEIGHTS,
        engine=ENGINE_VERSION,
    )


# ---------------------- JSON APIs ----------------------

def _public_match_result(outcome):
    """Browser-safe form of a match outcome (property snapshot, no internals)."""
    return {
        "count_considered": outcome["count_considered"],
        "count_eligible": outcome["count_eligible"],
        "no_match": outcome["no_match"],
        "message": outcome["message"],
        "engine": outcome["engine"],
        "threshold": outcome["threshold"],
        "criteria": outcome["criteria"],
        "results": [
            {
                "property_id": item["property"].get("id"),
                "name": item["property"].get("name"),
                "location": item["property"].get("location"),
                "price": item["property"].get("price"),
                "bedrooms": item["property"].get("bedrooms"),
                "match_score": item["match_score"],
                "reasons": item["reasons"],
                "mismatches": item["mismatches"],
            }
            for item in outcome["results"]
        ],
    }


@app.route("/api/ai/status")
@login_required
def api_ai_status():
    """Which AI providers are configured (booleans only — never key material)."""
    if not (can(g.get("user"), "assistant.use") or can(g.get("user"), "leads.create")):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(provider_status())


@app.route("/api/leads/analyse", methods=["POST"])
@login_required
def api_analyse_lead():
    """FR-02 API — extract structured requirements from enquiry text."""
    if not can(g.get("user"), "leads.create"):
        return jsonify({"error": "Forbidden"}), 403
    if not analysis_limiter.allow(request.remote_addr or "unknown"):
        return jsonify({"error": "Too many requests"}), 429

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object"}), 400
    try:
        result = analyse_enquiry(
            payload.get("enquiry", ""), provider=payload.get("provider") or None,
        )
    except EnquiryValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except AiProviderError:
        return jsonify({"error": "Analysis service unavailable"}), 502

    audit("lead.analyse", entity_type="lead",
          details=f"api provider={result['provider']} degraded={result['degraded']}")
    return jsonify({
        "provider": result["provider"],
        "model": result["model"],
        "degraded": result["degraded"],
        "elapsed_ms": result["elapsed_ms"],
        "enquiry_length": result["enquiry_length"],
        "fields": result["fields"],
        "missing_fields": result["missing_fields"],
        "clarification_questions": result["clarification_questions"],
        "warnings": result["warnings"],
    })


@app.route("/api/leads/<int:lead_id>/recommendations", methods=["GET", "POST"])
@login_required
def api_lead_recommendations(lead_id):
    """FR-06 API — persisted recommendations (GET) or a fresh run (POST)."""
    if not can(g.get("user"), "leads.view"):
        return jsonify({"error": "Forbidden"}), 403
    lead = get_lead(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    if not _can_view_lead(lead):
        return jsonify({"error": "Forbidden"}), 403

    if request.method == "GET":
        latest = get_latest_recommendations(lead_id)
        return jsonify({
            "lead_id": lead_id,
            "count": len(latest),
            "recommendations": latest,
        })

    outcome = _generate_recommendations(lead)
    audit("lead.match", entity_type="lead", entity_id=lead_id,
          details=f"api results={len(outcome['results'])}")
    return jsonify(_public_match_result(outcome))


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
