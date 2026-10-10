/* =========================================================
   filters.js — Instant property filtering on the list page
   The form still works without JS (server-side GET filter);
   with JS, cards show/hide immediately using the same rules.
   Also powers the local (browser-only) favourites feature.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("filterForm");
    const grid = document.getElementById("propertiesGrid");
    if (!form || !grid) return;

    const cards = Array.from(grid.querySelectorAll(".property-card"));
    const emptyRow = document.getElementById("filterEmpty");
    const countEl = document.getElementById("resultCount");
    const clearBtn = document.getElementById("clearFilters");

    /* ---------- favourites (localStorage only, no backend writes) ---------- */
    const FAV_KEY = "lyka:favourites";
    function getFavs() {
        try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
        catch (err) { return []; }
    }
    function isFav(id) { return getFavs().indexOf(String(id)) !== -1; }

    function initFavs() {
        grid.querySelectorAll(".property-fav").forEach(function (btn) {
            const active = isFav(btn.getAttribute("data-fav"));
            btn.classList.toggle("is-active", active);
            btn.setAttribute("aria-pressed", active ? "true" : "false");
        });
    }

    /* ---------- filtering ---------- */
    function val(name) {
        const el = form.elements[name];
        return el ? String(el.value || "").trim() : "";
    }

    function applyFilters() {
        const q = val("q").toLowerCase();
        const location = val("location").toLowerCase();
        const status = val("status");
        const view = val("view");
        const type = val("type").toLowerCase();
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
            if (ok && type && (d.type || "").toLowerCase() !== type) ok = false;
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
       except on links/buttons/forms inside the card. The favourite
       heart is handled first so it never triggers navigation. */
    grid.addEventListener("click", function (e) {
        const fav = e.target.closest(".property-fav");
        if (fav) {
            const id = fav.getAttribute("data-fav");
            const active = isFav(id);
            let favs = getFavs();
            if (active) {
                favs = favs.filter(function (x) { return x !== String(id); });
            } else {
                favs.push(String(id));
            }
            try { localStorage.setItem(FAV_KEY, JSON.stringify(favs)); }
            catch (err) { /* storage unavailable — toggle for this session */ }
            fav.classList.toggle("is-active", !active);
            fav.setAttribute("aria-pressed", active ? "false" : "true");
            e.stopPropagation();
            return;
        }

        if (e.target.closest("a, button, form")) return;
        const card = e.target.closest(".property-card");
        if (!card) return;
        const link = card.querySelector(".property-thumb-link") ||
                     card.querySelector(".property-thumb[href]");
        if (link) window.location.href = link.getAttribute("href");
    });

    /* If a thumbnail fails to load, first try the local scene image the
       card was given as a fallback (used for uploaded photos), then fall
       back to the built-in placeholder. */
    grid.addEventListener("error", function (e) {
        const t = e.target;
        if (!(t instanceof HTMLImageElement)) return;
        if (!t.classList.contains("property-thumb-img")) return;
        const fallback = t.getAttribute("data-fallback");
        if (fallback) {
            t.removeAttribute("data-fallback");
            t.src = fallback;
            return;
        }
        const span = document.createElement("span");
        span.className = "property-thumb-empty";
        span.setAttribute("title", "No photo");
        span.textContent = "🏠";
        t.replaceWith(span);
    }, true);

    /* Initial pass keeps client and server views in sync */
    initFavs();
    applyFilters();
});