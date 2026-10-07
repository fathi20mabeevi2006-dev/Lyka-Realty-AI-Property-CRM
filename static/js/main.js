/* =========================================================
   main.js — Sidebar toggle, flash auto-hide, small UX helpers
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    /* ---------- Mobile sidebar toggle ---------- */
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");
    const toggle = document.getElementById("menuToggle");

    function closeSidebar() {
        if (!sidebar) return;
        sidebar.classList.remove("open");
        if (overlay) overlay.classList.remove("open");
    }

    function openSidebar() {
        if (!sidebar) return;
        sidebar.classList.add("open");
        if (overlay) overlay.classList.add("open");
    }

    if (toggle) {
        toggle.addEventListener("click", function () {
            if (sidebar.classList.contains("open")) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    if (overlay) {
        overlay.addEventListener("click", closeSidebar);
    }

    /* Close sidebar when a nav link is clicked (mobile) */
    document.querySelectorAll(".sidebar .nav-item").forEach(function (item) {
        item.addEventListener("click", function () {
            if (window.innerWidth <= 900) closeSidebar();
        });
    });

    /* ---------- Auto-hide flash messages ---------- */
    document.querySelectorAll(".flash").forEach(function (el) {
        setTimeout(function () {
            el.style.transition = "opacity 0.4s ease, transform 0.4s ease";
            el.style.opacity = "0";
            el.style.transform = "translateY(-6px)";
            setTimeout(function () {
                el.remove();
            }, 400);
        }, 4000);
    });
});
