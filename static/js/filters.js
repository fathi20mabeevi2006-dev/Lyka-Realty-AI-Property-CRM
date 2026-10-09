/* =========================================================
   filters.js — Instant property filtering on the list page
   The form still works without JS (server-side GET filter);
   with JS, cards show/hide immediately using the same rules.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("filterForm");
    const grid = document.getElementById("propertiesGrid");
    if (!form || !grid) return;

    const cards = Array.from(grid.querySelectorAll(".property-card"));
    const emptyRow = document.getElementById("filterEmpty");
    const countEl = document.getElementById("resultCount");
    const clearBtn = document.getElementById("clearFilters");

    function val(name) {
        const el = form.elements[name];
        return el ? String(el.value || "").trim() : "";
    }

    function applyFilters() {
        const q = val("q").toLowerCase();
        const location = val("location").toLowerCase();
        const status = val("status");
        const view = val("view");
        const pool = val("pool");
        const metro = val("metro");
        const beds = val("bedrooms");
        const baths = val("bathrooms");
        const min = parseFloat(val("min_price"));
        const max = parseFloat(val("max_price"));

        let visible = 0;

        cards.forEach(function (card) {
            const d = card.dataset;
            let ok = true;

            if (q) {
                const hay = (d.name + " " + d.location).toLowerCase();
                if (hay.indexOf(q) === -1) ok = false;
            }
            if (ok && location && (d.location || "").toLowerCase().indexOf(location) === -1) ok = false;
            if (ok && status && d.status !== status) ok = false;
            if (ok && view) {
                if (view === "None" ? (d.view || "") !== "" : d.view !== view) ok = false;
            }
            if (ok && !isNaN(min) && parseFloat(d.price) < min) ok = false;
            if (ok && !isNaN(max) && parseFloat(d.price) > max) ok = false;
            if (ok && beds !== "" && d.bedrooms !== beds) ok = false;
            if (ok && baths !== "" && d.bathrooms !== baths) ok = false;
            if (ok && pool && d.pool !== pool) ok = false;
            if (ok && metro && d.metro !== metro) ok = false;

            card.style.display = ok ? "" : "none";
            if (ok) visible += 1;
        });

        if (emptyRow) emptyRow.style.display = visible === 0 ? "" : "none";
        if (countEl) {
            countEl.textContent =
                visible + " propert" + (visible === 1 ? "y" : "ies");
        }
    }

    /* Prevent a full page reload when JS is available */
    form.addEventListener("submit", function (e) {
        e.preventDefault();
        applyFilters();
    });

    /* Selects apply immediately on change */
    form.querySelectorAll("select").forEach(function (el) {
        el.addEventListener("change", applyFilters);
    });

    /* Text/number inputs apply after a short pause (debounce) */
    let timer = null;
    form.querySelectorAll("input").forEach(function (el) {
        el.addEventListener("input", function () {
            clearTimeout(timer);
            timer = setTimeout(applyFilters, 300);
        });
    });

    /* Clear all: reset form instantly (href fallback still works without JS) */
    if (clearBtn) {
        clearBtn.addEventListener("click", function (e) {
            e.preventDefault();
            form.reset();
            applyFilters();
        });
    }

    /* Clicking anywhere on a card opens the property detail page,
       except on links/buttons/forms inside the card. */
    grid.addEventListener("click", function (e) {
        if (e.target.closest("a, button, form")) return;
        const card = e.target.closest(".property-card");
        if (!card) return;
        const link = card.querySelector(".property-thumb");
        if (link) window.location.href = link.getAttribute("href");
    });

    /* If a thumbnail image fails to load (uploaded photo or sample
       illustration missing), fall back to the existing placeholder. */
    grid.addEventListener("error", function (e) {
        const t = e.target;
        if (!(t instanceof HTMLImageElement)) return;
        if (!t.classList.contains("property-thumb-img")) return;
        const span = document.createElement("span");
        span.className = "property-thumb-empty";
        span.setAttribute("title", "No photo");
        span.textContent = "🏠";
        t.replaceWith(span);
    }, true);

    /* Initial pass keeps client and server views in sync */
    applyFilters();
});