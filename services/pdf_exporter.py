"""
services/pdf_exporter.py
Phase 4 — renders the BRD document model (brd.py) into a PDF.

If the `fpdf2` library is not installed the module still imports fine:
    - pdf_available() returns False
    - export_brd_pdf() raises RuntimeError (the app catches this in the
      route and tells the user what to install instead of crashing).

The preview page (templates/brd.html) and this exporter render the SAME
document model, so their content always matches.
"""

try:
    from fpdf import FPDF

    PDF_AVAILABLE = True
except Exception:  # pragma: no cover - only reachable when fpdf2 is missing
    FPDF = None
    PDF_AVAILABLE = False


def pdf_available():
    """True when the fpdf2 library is installed and importable."""
    return PDF_AVAILABLE


def _clean(text):
    """Make arbitrary user text safe for the PDF's latin-1 core fonts.

    Removes control characters and replaces anything outside latin-1 (e.g.
    Arabic, emoji, smart quotes) with '?', so a non-ASCII note can never
    crash the export.
    """
    if text is None:
        return ""
    safe = "".join(
        ch for ch in str(text) if ch >= " " or ch in "\n\t"
    )
    return safe.encode("latin-1", "replace").decode("latin-1")


def _mc(pdf, height, text):
    """multi_cell that always returns the cursor to the left margin.

    fpdf2's multi_cell leaves the cursor at the right margin by default;
    without resetting it the NEXT multi_cell would have zero width and crash.
    new_x/new_y also keep automatic page breaks working as expected. Every
    string passes through _clean() so non-latin-1 characters can never crash
    the export.
    """
    pdf.multi_cell(0, height, _clean(text), new_x="LMARGIN", new_y="NEXT")


def _fill(words):
    """Join words squashing whitespace/newlines to single spaces."""
    return " ".join(str(words or "").split())


def _tags(parts):
    """Render a '[..] · [..]' tag line from truthy parts."""
    return " · ".join(f"[{p}]" for p in parts if p)


def _bullet(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(31, 41, 55)
    _mc(pdf, 5.2, _fill(text))
    pdf.ln(1.2)


def _empty_note(pdf):
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(110, 110, 110)
    _mc(pdf, 5.2, "(nothing documented yet - see section 'Missing Information')")
    pdf.ln(1.5)


def _section(pdf, heading):
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(31, 41, 55)
    _mc(pdf, 6.5, heading)
    pdf.set_draw_color(203, 213, 225)
    y = pdf.get_y() + 0.5
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)


def _subtext(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(31, 41, 55)
    _mc(pdf, 5.2, _fill(text))
    pdf.ln(1.2)


def _render_entry(pdf, entry):
    head = entry["title"]
    _bullet(pdf, f"• {head} - {entry['details'] or 'not documented'}")
    _subtext(pdf, _tags([
        f"Category: {entry['category']}", f"Source: {entry['source_type']}",
        f"Status: {entry['status']}",
    ]))
    pdf.ln(0.8)


def _render_requirement(pdf, req):
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(31, 41, 55)
    _mc(pdf, 5.2, _fill(req["title"]))
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(110, 110, 110)
    _mc(pdf, 4.6, _fill(
        f"[Priority: {req['priority']}]  [Status: {req['status']}]"
    ))
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(31, 41, 55)
    pdf.ln(0.8)

    if req.get("owner"):
        _subtext(pdf, _tags([f"Owner: {req['owner']}",
                             f"Category: {req['category']}"]))
    if req["description"]:
        _bullet(pdf, f"Description: {req['description']}")
    if req["problem"]:
        _bullet(pdf, f"Problem: {req['problem']}")
    if req["proposed_solution"]:
        _bullet(pdf, f"Proposed solution: {req['proposed_solution']}")
    if req["acceptance_criteria"]:
        _bullet(pdf, f"Acceptance criteria: {req['acceptance_criteria']}")
    if req["current_state"] or req["desired_state"]:
        _bullet(pdf, f"Current state: {req['current_state'] or 'not documented'}")
        _bullet(pdf, f"Desired state: {req['desired_state'] or 'not documented'}")
    if req["gap_notes"]:
        _bullet(pdf, f"Gap notes: {req['gap_notes']}")
    if req["dependencies"] or req["risks"]:
        _bullet(pdf, f"Dependencies: {req['dependencies'] or 'none documented'}")
        _bullet(pdf, f"Risks: {req['risks'] or 'none documented'}")
    pdf.ln(1.5)


class _BrdPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def export_brd_pdf(doc):
    """Render the BRD document model to PDF bytes.

    Raises RuntimeError when fpdf2 is not installed.
    """
    if not PDF_AVAILABLE:
        raise RuntimeError(
            "PDF export is unavailable because the 'fpdf2' library is not "
            "installed. Install it with:  pip install fpdf2"
        )
    if FPDF is None:  # unreachable, kept for type safety / clarity
        raise RuntimeError("PDF export is unavailable (fpdf2 missing).")

    pdf = _BrdPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(16, 16, 16)
    pdf.add_page()

    # ------------------------------------------------------------ title block
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(31, 41, 55)
    _mc(pdf, 8.5, _clean(doc["meta"]["title"]))
    pdf.set_font("Helvetica", "B", 13)
    _mc(pdf, 6, _clean(doc["meta"]["company"]))
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(110, 110, 110)
    _mc(pdf, 5, _clean(
        f"Prepared automatically on {doc['meta']['generated_at']} "
        f"({doc['meta']['generated_by']})."
    ))
    _mc(pdf, 5, _clean(doc["meta"]["source_note"]))
    pdf.ln(3)

    # ------------------------------------------------------ 1. current state
    _section(pdf, "1. Current State (Verified Facts)")
    _subtext(pdf, doc["current_state"]["stats_label"])
    for item in doc["current_state"]["facts"]:
        _bullet(pdf, f"{item['label']}: {item['value']} - {item['note']}")

    # ------------------------------------------------------ 2. company profile
    _section(pdf, "2. Company Profile")
    if doc["company_profile"]:
        for entry in doc["company_profile"]:
            _render_entry(pdf, entry)
    else:
        _empty_note(pdf)

    # ------------------------------------------------------ 3. objectives
    _section(pdf, "3. Business Objectives")
    if doc["objectives"]:
        for entry in doc["objectives"]:
            _render_entry(pdf, entry)
    else:
        _empty_note(pdf)

    # ------------------------------------------- 4/5/6. facts/assumptions/recs
    for heading, items in (
        ("4. Documented Facts", doc["fact_base"]),
        ("5. Assumptions", doc["assumptions"]),
        ("6. Recommendations", doc["recommendations"]),
    ):
        _section(pdf, heading)
        if items:
            for entry in items:
                _render_entry(pdf, entry)
        else:
            _empty_note(pdf)

    # ------------------------------------------- 7/8. problems & solutions
    for heading, items in (
        ("7. Identified Business Problems", doc["problems"]),
        ("8. Proposed Solutions", doc["solutions"]),
    ):
        _section(pdf, heading)
        if items:
            for item in items:
                tags = _tags([f"Priority: {item['priority']}",
                              f"Status: {item['status']}"])
                _bullet(
                    pdf,
                    f"• {item['title']} - {item['text'] or 'not documented'} {tags}",
                )
        else:
            _empty_note(pdf)

    # ------------------------------------------- 9/10. requirements
    for heading, reqs in (
        ("9. Functional Requirements", doc["functional"]),
        ("10. Non-Functional Requirements", doc["non_functional"]),
    ):
        _section(pdf, heading)
        if reqs:
            for req in reqs:
                _render_requirement(pdf, req)
        else:
            _empty_note(pdf)

    # ------------------------------------------------------ 11. gap summary
    _section(pdf, "11. Gap Analysis Summary")
    gap = doc["gap_summary"]
    _bullet(
        pdf,
        f"{gap['total']} requirement(s) considered; {gap['gap_count']} "
        "gap(s) identified (current state differs from desired state).",
    )
    if gap["gaps"]:
        for item in gap["gaps"]:
            tags = _tags([f"Priority: {item['priority']}",
                          f"Status: {item['status']}"])
            _bullet(pdf, f"• {item['title']} {tags}")
    else:
        _empty_note(pdf)

    # -------------------------------------------------- 12. missing information
    _section(pdf, "12. Missing Information")
    if doc["missing"]:
        for text in doc["missing"]:
            _bullet(pdf, f"• {text}")
    else:
        _bullet(pdf, "No missing information detected in the current notes "
                     "and requirements.")

    return pdf.output(dest="S")


if __name__ == "__main__":  # pragma: no cover - simple CLI smoke check
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import brd

    data = brd.build_brd()
    print("PDF available:", pdf_available())
    out = export_brd_pdf(data)
    print("PDF bytes:", len(out), "| starts with:", out[:4])