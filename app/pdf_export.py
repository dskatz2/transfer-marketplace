"""Branded PDF exports for sales use: contract history + matching opportunities.

Built with reportlab (pure Python) + svglib (pure Python + lxml) to render the
bundled Seso logo SVG directly as a vector flowable - deliberately not
weasyprint/cairosvg, which need system-level Cairo/Pango and are exactly the
kind of dependency that's painful to get working in a serverless environment
like Vercel (see the app/database.py and vercel.json history on this project).
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from svglib.svglib import svg2rlg

# ---------- Brand (pulled from sesolabor.com) ----------

GREEN = colors.HexColor("#006E33")
GREEN_LIGHT_BG = colors.HexColor("#EAF7EF")
INK = colors.HexColor("#181C1F")
MUTED = colors.HexColor("#6B7280")
BORDER = colors.HexColor("#E2E5EA")
WHITE = colors.white

LOGO_PATH = Path(__file__).parent / "data" / "seso_logo.svg"

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("SesoH1", parent=_styles["Heading1"], fontName="Helvetica-Bold", fontSize=20, textColor=INK, spaceAfter=4)
SUBTITLE = ParagraphStyle("SesoSubtitle", parent=_styles["Normal"], fontName="Helvetica", fontSize=9.5, textColor=MUTED, spaceAfter=14)
H2 = ParagraphStyle("SesoH2", parent=_styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=GREEN, spaceBefore=16, spaceAfter=6)
BODY = ParagraphStyle("SesoBody", parent=_styles["Normal"], fontName="Helvetica", fontSize=9.5, textColor=INK, leading=13)
CELL = ParagraphStyle("SesoCell", parent=_styles["Normal"], fontName="Helvetica", fontSize=8.5, textColor=INK, leading=11)
CELL_SUB = ParagraphStyle("SesoCellSub", parent=CELL, fontSize=7.5, textColor=MUTED)
KPI_VALUE = ParagraphStyle("SesoKpiValue", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=15, textColor=INK, alignment=TA_CENTER)
KPI_LABEL = ParagraphStyle("SesoKpiLabel", parent=_styles["Normal"], fontName="Helvetica", fontSize=7.5, textColor=MUTED, alignment=TA_CENTER)


def _logo_drawing(target_width: float = 110):
    drawing = svg2rlg(str(LOGO_PATH))
    scale = target_width / drawing.width
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    return drawing


def _fmt_date(iso_or_date) -> str:
    d = date.fromisoformat(iso_or_date) if isinstance(iso_or_date, str) else iso_or_date
    return d.strftime("%b %-d, %Y")


def _stack(main: str, sub: str | None) -> Paragraph:
    text = _xml_escape(main or "")
    if sub:
        text += f"<br/><font color='#6B7280' size=7.5>{_xml_escape(sub)}</font>"
    return Paragraph(text, CELL)


def _cell(value) -> Paragraph:
    """Every table cell must go through this (or _stack) - a plain string in a
    reportlab Table cell does NOT wrap to fit its column the way HTML does, it
    just overflows straight into the next cell. Only Paragraph objects wrap."""
    return Paragraph(_xml_escape(str(value)), CELL)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Confidential — prepared by Seso")
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _header_flowables(title: str, subtitle: str) -> list:
    """subtitle is treated as pre-formatted/trusted (callers only pass static
    templates); title is arbitrary (a real company name) and gets escaped."""
    return [
        _logo_drawing(),
        Spacer(1, 8),
        Paragraph(_xml_escape(title), H1),
        Paragraph(subtitle, SUBTITLE),
        HRFlowable(width="100%", thickness=2, color=GREEN, spaceAfter=14),
    ]


def _table(data, col_widths) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GREEN_LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


class Anonymizer:
    """Replaces real company names with consistent generic labels ("Customer A",
    "Prospect B", ...) within one document, and - when a party is anonymized -
    reduces its worksite location to state-only so it can't be re-identified
    from city + worker count + job type."""

    def __init__(self, anonymize_customers: bool, anonymize_prospects: bool):
        self.anon_customers = anonymize_customers
        self.anon_prospects = anonymize_prospects
        self._labels: dict[str, str] = {}
        self._counts = {"Customer": 0, "Prospect": 0}

    def _label(self, real_name: str, kind: str) -> str:
        key = f"{kind}:{real_name}"
        if key not in self._labels:
            n = self._counts[kind]
            letter = chr(65 + n) if n < 26 else str(n + 1)
            self._labels[key] = f"{kind} {letter}"
            self._counts[kind] += 1
        return self._labels[key]

    def is_customer(self, contract: dict) -> bool:
        return bool(contract.get("enterprise"))

    def name(self, contract: dict) -> str:
        is_cust = self.is_customer(contract)
        real = contract["enterprise"]["name"] if is_cust else contract["employer_name"]
        should = self.anon_customers if is_cust else self.anon_prospects
        return self._label(real, "Customer" if is_cust else "Prospect") if should else real

    def location(self, contract: dict) -> str:
        should = self.anon_customers if self.is_customer(contract) else self.anon_prospects
        city, state = contract.get("worksite_city"), contract.get("worksite_state")
        if should:
            return state or "—"
        if city and state:
            return f"{city}, {state}"
        return state or city or "—"


def _contract_history_table(contracts: list[dict], anon: Anonymizer) -> Table:
    today = date.today()
    rows = [["Status", "Job Title", "Location", "Dates", "Workers"]]
    for c in contracts:
        end = date.fromisoformat(c["contract_end"])
        status = "Upcoming" if end >= today else "Past"
        qualifies = "" if c.get("qualifies_for_matching") else " (< 25)"
        rows.append([
            _cell(status),
            _cell(c["job_title"] or "—"),
            _cell(anon.location(c)),
            _cell(f'{_fmt_date(c["contract_start"])} → {_fmt_date(c["contract_end"])}'),
            _cell(f'{c["worker_count"]}{qualifies}'),
        ])
    return _table(rows, [55, 140, 80, 125, 60])


def _matches_table(matches: list[dict], anon: Anonymizer) -> Table:
    rows = [["Direction", "Ending contract", "Starting contract", "Gap", "Distance", "Workers"]]
    for m in matches:
        distance = f'{round(m["distance_miles"])} mi' if m.get("distance_miles") is not None else "—"
        rows.append([
            _cell(m.get("direction", "")),
            _stack(anon.name(m["from"]), anon.location(m["from"])),
            _stack(anon.name(m["to"]), anon.location(m["to"])),
            _cell(f'{m["gap_days"]}d'),
            _cell(distance),
            _cell(m["transferable_workers"]),
        ])
    return _table(rows, [72, 122, 122, 30, 52, 48])


def build_prospect_pdf(
    employer_name: str,
    contracts: list[dict],
    matches: list[dict],
    anonymize_customers: bool,
    anonymize_prospects: bool,
    matches_total: int | None = None,
) -> bytes:
    anon = Anonymizer(anonymize_customers, anonymize_prospects)
    is_customer = any(c.get("enterprise") for c in contracts)
    header_contract = {
        "enterprise": {"name": employer_name} if is_customer else None,
        "employer_name": employer_name,
    }
    display_name = anon.name(header_contract)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title=f"{display_name} - Seso",
    )

    story = list(_header_flowables(
        display_name,
        f"Contract history &amp; transfer matching overview · Generated {datetime.now().strftime('%B %-d, %Y')}",
    ))

    story.append(Paragraph("Contract History", H2))
    if contracts:
        story.append(_contract_history_table(contracts, anon))
    else:
        story.append(Paragraph("No filings on record.", BODY))

    story.append(Paragraph("Matching Opportunities", H2))
    if matches:
        if matches_total and matches_total > len(matches):
            story.append(Paragraph(f"Showing the top {len(matches)} of {matches_total} matches, ranked by transferable workers.", SUBTITLE))
        story.append(_matches_table(matches, anon))
    else:
        story.append(Paragraph("No current transfer-window matches for this company's qualifying contracts.", BODY))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def build_dashboard_pdf(
    kpis: dict,
    cc_matches: list[dict],
    cp_matches: list[dict],
    anonymize_customers: bool,
    anonymize_prospects: bool,
) -> bytes:
    anon = Anonymizer(anonymize_customers, anonymize_prospects)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title="Top Transfer Opportunities - Seso",
    )

    story = list(_header_flowables(
        "Top Transfer Opportunities",
        f"Generated {datetime.now().strftime('%B %-d, %Y')}",
    ))

    kpi_cells = [
        (f'{kpis["total_open_matches"]:,}', "Open matches"),
        (f'{kpis["total_transferable_workers"]:,}', "Workers w/ live option"),
        (str(kpis["customers_with_opportunity"]), "Customers involved"),
        (f'{kpis["avg_gap_days"]} days', "Avg. transfer gap"),
    ]
    kpi_table = Table(
        [[Paragraph(v, KPI_VALUE) for v, _ in kpi_cells], [Paragraph(l, KPI_LABEL) for _, l in kpi_cells]],
        colWidths=[122] * 4,
    )
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
    ]))
    story.append(kpi_table)

    def _plain_matches_table(matches: list[dict]) -> Table:
        rows = [["Ending contract", "Starting contract", "Gap", "Distance", "Workers"]]
        for m in matches:
            distance = f'{round(m["distance_miles"])} mi' if m.get("distance_miles") is not None else "—"
            rows.append([
                _stack(anon.name(m["from"]), anon.location(m["from"])),
                _stack(anon.name(m["to"]), anon.location(m["to"])),
                _cell(f'{m["gap_days"]}d'),
                _cell(distance),
                _cell(m["transferable_workers"]),
            ])
        return _table(rows, [155, 155, 35, 55, 55])

    story.append(Paragraph("Seso Customer ↔ Seso Customer Matches", H2))
    story.append(_plain_matches_table(cc_matches) if cc_matches else Paragraph("None currently.", BODY))

    story.append(Paragraph("Seso Customer ↔ Prospect Matches", H2))
    story.append(_plain_matches_table(cp_matches) if cp_matches else Paragraph("None currently.", BODY))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
