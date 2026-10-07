/* =========================================================
   filters.js — Instant property filtering on the list page
   The form still works without JS (server-side GET filter);
   with JS, rows show/hide immediately using the same rules.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("filterForm");
    const table = document.getElementById("propertiesTable");
    if (!form || !table) return;

    const rows = Array.from(table.querySelectorAll("tbody tr")).filter(function (r) {
        return r.id !== "filterEmpty";
    });
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

        rows.forEach(function (row) {
            const d = row.dataset;
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

            row.style.display = ok ? "" : "none";
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

    /* Initial pass keeps client and server views in sync */
    applyFilters();
});
