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
    url_for, flash, jsonify,
)
import os
import uuid

from database import (
    init_db, get_all_properties, get_property, add_property,
    update_property, delete_property, get_all_leads, get_lead,
    add_lead, update_lead, delete_lead, get_dashboard_stats,
    add_property_images, get_property_images, get_property_image,
    delete_property_image,
)
from ai_assistant import answer_question
from seed_data import seed

app = Flask(__name__)
app.secret_key = "property-crm-secret-key-change-me"

# --- image upload settings ---
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
UPLOAD_FOLDER = os.path.join(app.static_folder, "uploads", "properties")
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB per request
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


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


# ---------------------- HOME / DASHBOARD ----------------------

@app.route("/")
def dashboard():
    stats = get_dashboard_stats()
    properties = get_all_properties()[:6]
    leads = get_all_leads()[:5]
    return render_template(
        "dashboard.html",
        stats=stats,
        properties=properties,
        leads=leads,
    )


# ---------------------- PROPERTIES CRUD ----------------------

@app.route("/properties")
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
def add_property_page():
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            property_id = add_property(data)
            filenames = save_property_images(request.files.getlist("images"))
            add_property_images(property_id, filenames)
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
def delete_property_page(property_id):
    filenames = delete_property(property_id)
    for filename in filenames:
        remove_image_file(filename)
    flash("Property deleted.", "info")
    return redirect(url_for("properties_page"))


@app.route(
    "/properties/<int:property_id>/images/<int:image_id>/delete",
    methods=["POST"],
)
def delete_property_image_page(property_id, image_id):
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
def leads_page():
    status = request.args.get("status", "")
    q = request.args.get("q", "")
    items = get_all_leads()

    if status:
        items = [l for l in items if l["status"] == status]
    if q:
        ql = q.lower()
        items = [
            l for l in items
            if ql in l["client_name"].lower() or ql in (l["email"] or "").lower()
            or ql in (l["phone"] or "")
        ]

    return render_template("leads.html", leads=items, status=status, q=q)


@app.route("/leads/new", methods=["GET", "POST"])
def add_lead_page():
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            add_lead(data)
            flash("Lead added successfully!", "success")
            return redirect(url_for("leads_page"))
        except (ValueError, TypeError):
            flash("Please fill in the client name correctly.", "error")
            return render_template("lead_form.html", lead=None, action="add")

    return render_template("lead_form.html", lead=None, action="add")


@app.route("/leads/<int:lead_id>/edit", methods=["GET", "POST"])
def edit_lead_page(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("leads_page"))

    if request.method == "POST":
        data = request.form.to_dict()
        try:
            update_lead(lead_id, data)
            flash("Lead updated successfully!", "success")
            return redirect(url_for("leads_page"))
        except (ValueError, TypeError):
            flash("Please fill in the client name correctly.", "error")
            return render_template("lead_form.html", lead=lead, action="edit")

    return render_template("lead_form.html", lead=lead, action="edit")


@app.route("/leads/<int:lead_id>/delete", methods=["POST"])
def delete_lead_page(lead_id):
    delete_lead(lead_id)
    flash("Lead deleted.", "info")
    return redirect(url_for("leads_page"))


# ---------------------- AI ASSISTANT ----------------------

@app.route("/assistant")
def assistant_page():
    return render_template("assistant.html")


@app.route("/api/assistant", methods=["POST"])
def assistant_api():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    reply = answer_question(message)
    return jsonify({"reply": reply})


# ---------------------- RUN ----------------------

if __name__ == "__main__":
    seed()
    app.run(debug=True, port=5000)
