"""
utils/report_gen.py — Smart Resume Analyzer
=============================================
Generates a 2-page PDF analysis report using ReportLab.

Page 1 — Summary + Skill Breakdown
    Header card · Score dial · Category bars · Stats row · Matched skills

Page 2 — Gaps + Recommendations + Next Steps
    Missing skills · Alternative roles · Next steps · Disclaimer

Usage:
    from utils.report_gen import generate
    path = generate(analysis_id, result, user_name, role_name, report_dir)

Install:
    pip install reportlab
"""

import os
from datetime import datetime, timezone

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether, PageBreak,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus.flowables import Flowable
except ImportError:
    raise ImportError("ReportLab not installed.\nRun: pip install reportlab")


# ── Colours ───────────────────────────────────────────────────────────────────
INDIGO        = HexColor("#3730A3")
INDIGO_DIM    = HexColor("#EEF2FF")
INDIGO_BORDER = HexColor("#C7D2FE")
CORAL         = HexColor("#F4622A")
CORAL_DIM     = HexColor("#FFF1EC")
SUCCESS       = HexColor("#059669")
SUCCESS_BG    = HexColor("#ECFDF5")
SUCCESS_BDR   = HexColor("#6EE7B7")
ERROR         = HexColor("#DC2626")
ERROR_BG      = HexColor("#FEF2F2")
ERROR_BDR     = HexColor("#FCA5A5")
WARN          = HexColor("#D97706")
WARN_BG       = HexColor("#FFFBEB")
WARN_BDR      = HexColor("#FCD34D")
SURFACE       = HexColor("#F9FAFB")
BORDER        = HexColor("#E5E7EB")
MUTED         = HexColor("#6B7280")
DARK          = HexColor("#1F2937")
MIDNIGHT      = HexColor("#111827")

W, H  = A4          # 595.27 × 841.89 pt
ML    = 18 * mm     # left/right margin
MT    = 16 * mm     # top margin (below header bar)
MB    = 12 * mm     # bottom margin (above footer bar)
CW    = W - 2 * ML  # content width ≈ 159 mm


# ── Score helpers ─────────────────────────────────────────────────────────────

def _sc(score):
    """Return (color, bg_color, border_color, label) for a score."""
    if score >= 70:
        return SUCCESS, SUCCESS_BG, SUCCESS_BDR, "Strong Match"
    if score >= 40:
        return WARN, WARN_BG, WARN_BDR, "Moderate Match"
    return ERROR, ERROR_BG, ERROR_BDR, "Needs Work"


# ── Styles ────────────────────────────────────────────────────────────────────

def _S():
    """Return style dict. Each call creates fresh instances."""
    def p(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "h1"    : p("rh1", fontName="Helvetica-Bold",  fontSize=16,
                    textColor=MIDNIGHT, leading=20, spaceAfter=2),
        "sub"   : p("rsub", fontName="Helvetica",      fontSize=8.5,
                    textColor=MUTED,    leading=12, spaceAfter=0),
        "h2"    : p("rh2", fontName="Helvetica-Bold",  fontSize=11,
                    textColor=INDIGO,   leading=15, spaceBefore=10, spaceAfter=4),
        "h3"    : p("rh3", fontName="Helvetica-Bold",  fontSize=9,
                    textColor=DARK,     leading=13, spaceBefore=6,  spaceAfter=3),
        "body"  : p("rbody", fontName="Helvetica",     fontSize=8.5,
                    textColor=DARK,     leading=13),
        "muted" : p("rmuted", fontName="Helvetica",    fontSize=7.5,
                    textColor=MUTED,    leading=11),
        "clabel": p("rclabel", fontName="Helvetica-Bold", fontSize=7.5,
                    textColor=MUTED,    leading=11, spaceAfter=2),
        "note"  : p("rnote", fontName="Helvetica",     fontSize=8,
                    textColor=DARK,     leading=12,
                    backColor=INDIGO_DIM, borderColor=INDIGO_BORDER,
                    borderWidth=0.5,    borderPadding=6),
        "ok"    : p("rok", fontName="Helvetica-Bold",  fontSize=8.5,
                    textColor=SUCCESS,  leading=13,
                    backColor=SUCCESS_BG, borderColor=SUCCESS_BDR,
                    borderWidth=0.5,    borderPadding=6),
        "disc"  : p("rdisc", fontName="Helvetica",     fontSize=7,
                    textColor=MUTED,    leading=10, alignment=TA_CENTER),
        "step"  : p("rstep", fontName="Helvetica",     fontSize=8.5,
                    textColor=DARK,     leading=13, leftIndent=10, spaceAfter=4),
    }


# ── Header / Footer (drawn on canvas, not in story) ──────────────────────────

def _draw_page(canvas, doc):
    canvas.saveState()

    # ── Top bar ───────────────────────────────────────────────────────────────
    canvas.setFillColor(INDIGO)
    canvas.rect(0, H - 12*mm, W, 12*mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica-Bold", 9.5)
    canvas.drawString(ML, H - 7.5*mm, "Smart Resume Analyzer")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(W - ML, H - 7.5*mm,
        datetime.now(timezone.utc).strftime("%d %b %Y"))

    # ── Bottom bar ────────────────────────────────────────────────────────────
    canvas.setFillColor(SURFACE)
    canvas.rect(0, 0, W, 9*mm, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(ML, 3.5*mm, "Confidential · Smart Resume Analyzer")
    canvas.drawRightString(W - ML, 3.5*mm, f"Page {doc.page} of 2")

    canvas.restoreState()


# ── ScoreDial flowable ────────────────────────────────────────────────────────

class ScoreDial(Flowable):
    """Circular arc dial — no overlap, all text inside the circle."""

    SIZE = 100   # bounding box width & height

    def __init__(self, score):
        Flowable.__init__(self)
        self.score  = score
        self.width  = self.SIZE
        self.height = self.SIZE

    def draw(self):
        score = self.score
        c     = self.canv
        sz    = self.SIZE
        cx    = sz / 2
        cy    = sz / 2
        r     = sz / 2 - 10    # radius, leaves 10pt padding all round
        col, bg, bdr, label = _sc(score)

        # White fill circle
        c.setFillColor(white)
        c.setStrokeColor(BORDER)
        c.setLineWidth(8)
        c.circle(cx, cy, r, fill=1, stroke=1)

        # Coloured arc (progress)
        c.setStrokeColor(col)
        c.setLineWidth(8)
        extent = -(score / 100) * 360
        c.arc(cx - r, cy - r, cx + r, cy + r, startAng=90, extent=extent)

        # Score number — centred, sized to fit inside r
        c.setFillColor(MIDNIGHT)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(cx, cy + 5, f"{score:.0f}%")

        # Label — one line, small, below the number
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawCentredString(cx, cy - 8, label)


# ── Skill row table helper ────────────────────────────────────────────────────

def _skill_table(skill_names, bg, border_col, text_col):
    """
    Lay out skill names in a compact table, 4 per row.
    Each cell is a Paragraph with coloured background.
    Fixed column width so nothing overflows.
    """
    col_w  = CW / 4
    pill_s = ParagraphStyle(
        "pill",
        fontName    = "Helvetica",
        fontSize    = 8,
        textColor   = text_col,
        backColor   = bg,
        borderColor = border_col,
        borderWidth = 0.5,
        borderPadding = (3, 5, 3, 5),   # top right bottom left
        leading     = 12,
        wordWrap    = "CJK",            # allow break anywhere if needed
    )

    rows  = []
    row   = []
    for name in skill_names:
        row.append(Paragraph(name, pill_s))
        if len(row) == 4:
            rows.append(row[:])
            row = []
    if row:
        # pad to 4 cols with empty strings
        row += [""] * (4 - len(row))
        rows.append(row)

    if not rows:
        return None

    tbl = Table(rows, colWidths=[col_w] * 4, repeatRows=0)
    tbl.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


# ── Page 1: Summary + Matched Skills ─────────────────────────────────────────

def _page1(result, user_name, role_name, S):
    story = []
    score = result["readiness_score"]
    col, bg, bdr, label = _sc(score)

    # ── Title block ───────────────────────────────────────────────────────────
    story.append(Paragraph("Resume Analysis Report", S["h1"]))
    story.append(Paragraph(
        f"Candidate: <b>{user_name}</b>  ·  Role Applied: <b>{role_name}</b>",
        S["sub"]
    ))
    story.append(HRFlowable(width="100%", thickness=0.8,
                             color=INDIGO_BORDER, spaceAfter=8, spaceBefore=6))

    # ── Score dial + breakdown bars (side by side) ────────────────────────────
    dial = ScoreDial(score)

    bar_w = CW * 0.60 - 8   # bar section width

    def bar_row(lbl, matched, total, bar_col):
        """Returns a list of flowables for one skill category bar."""
        pct   = (matched / total) if total else 0
        bk_w  = bar_w - 55   # actual bar track width
        items = [
            Paragraph(
                f'<b>{lbl}</b>  '
                f'<font color="#{MUTED.hexval()[2:]}">{matched}/{total}</font>',
                ParagraphStyle("brl", fontName="Helvetica", fontSize=8,
                               textColor=DARK, leading=11)
            ),
            Spacer(1, 2),
        ]
        return items

    # Build bar section as a canvas-drawn table column
    # Use a mini-table: label col + drawn bar col
    bar_rows = []
    for lbl, matched, total, bar_col in [
        ("Core Skills",      result["core_matched"],      result["core_total"],      SUCCESS),
        ("Secondary Skills", result["secondary_matched"], result["secondary_total"], INDIGO),
        ("Bonus Skills",     result["bonus_matched"],     result["bonus_total"],     CORAL),
    ]:
        pct    = (matched / total) if total else 0
        pct_s  = f"{matched}/{total}"
        lbl_p  = Paragraph(
            f'<b>{lbl}</b>',
            ParagraphStyle("bl", fontName="Helvetica-Bold", fontSize=8,
                           textColor=DARK, leading=11)
        )
        cnt_p  = Paragraph(
            pct_s,
            ParagraphStyle("bc", fontName="Helvetica", fontSize=8,
                           textColor=MUTED, leading=11, alignment=TA_RIGHT)
        )
        bar_rows.append([lbl_p, cnt_p])

    bar_tbl = Table(bar_rows, colWidths=[bar_w - 35, 35])
    bar_tbl.setStyle(TableStyle([
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))

    # Progress bars drawn via a custom Flowable
    class BarStack(Flowable):
        def __init__(self, data, width, height):
            Flowable.__init__(self)
            self.data   = data   # [(label, matched, total, color), ...]
            self.width  = width
            self.height = height

        def draw(self):
            c    = self.canv
            row_h = self.height / len(self.data)
            bh    = 7       # bar height
            lw    = 95      # label column width
            cw    = 28      # count column width
            bw    = self.width - lw - cw - 6  # bar track width

            for i, (lbl, matched, total, bar_col) in enumerate(self.data):
                y   = self.height - (i + 1) * row_h + (row_h - bh) / 2
                pct = (matched / total) if total else 0

                # Label
                c.setFillColor(DARK)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawString(0, y + 1, lbl)

                # Count — right-aligned in count column
                c.setFillColor(MUTED)
                c.setFont("Helvetica", 7.5)
                c.drawRightString(lw + cw, y + 1, f"{matched}/{total}")

                # Bar track
                c.setFillColor(BORDER)
                c.roundRect(lw + cw + 4, y, bw, bh, 3, fill=1, stroke=0)

                # Bar fill
                if pct > 0:
                    c.setFillColor(bar_col)
                    c.roundRect(lw + cw + 4, y, max(5, bw * pct), bh, 3,
                                fill=1, stroke=0)

    bars_flowable = BarStack(
        [
            ("Core Skills",      result["core_matched"],      result["core_total"],      SUCCESS),
            ("Secondary Skills", result["secondary_matched"], result["secondary_total"], INDIGO),
            ("Bonus Skills",     result["bonus_matched"],     result["bonus_total"],     CORAL),
        ],
        width  = CW * 0.60,
        height = 60,
    )

    dial_w = CW * 0.32
    bar_w2 = CW * 0.68

    layout = Table(
        [[dial, bars_flowable]],
        colWidths=[dial_w, bar_w2],
    )
    layout.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
    ]))
    story.append(layout)
    story.append(Spacer(1, 10))

    # ── Stats row ─────────────────────────────────────────────────────────────
    total_m = (result["core_matched"] + result["secondary_matched"]
               + result["bonus_matched"])
    total_s = (result["core_total"]   + result["secondary_total"]
               + result["bonus_total"])
    missing = total_s - total_m

    def _stat(val, lbl, vc):
        return [
            Paragraph(
                f'<font color="#{vc.hexval()[2:]}"><b>{val}</b></font>',
                ParagraphStyle("sv", fontName="Helvetica-Bold", fontSize=18,
                               alignment=TA_CENTER, textColor=vc, leading=22)
            ),
            Paragraph(
                lbl,
                ParagraphStyle("sl", fontName="Helvetica", fontSize=7.5,
                               alignment=TA_CENTER, textColor=MUTED, leading=10)
            ),
        ]

    st = Table(
        [[
            _stat(f"{score:.0f}%", "Readiness Score",   col),
            _stat(str(total_m),    "Skills Matched",     SUCCESS),
            _stat(str(missing),    "Skills Missing",     ERROR if missing else SUCCESS),
            _stat(f"{result['core_matched']}/{result['core_total']}",
                  "Core Skills",   INDIGO),
        ]],
        colWidths = [CW / 4] * 4,
    )
    st.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.5, BORDER),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, BORDER),
        ("BACKGROUND",    (0,0),(-1,-1), SURFACE),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("RIGHTPADDING",  (0,0),(-1,-1), 4),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(st)
    story.append(Spacer(1, 8))

    # ── AI prediction note ────────────────────────────────────────────────────
    pred = result.get("predicted_role", "")
    if pred and pred.lower() != role_name.lower():
        story.append(Paragraph(
            f'<b>AI Prediction:</b> Your resume also strongly matches '
            f'<b>{pred}</b> — consider exploring that role too.',
            S["note"]
        ))
        story.append(Spacer(1, 8))

    # ── Matched skills ────────────────────────────────────────────────────────
    matched = result["matched_skills"]
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=BORDER, spaceAfter=6))
    story.append(Paragraph(
        f'<font color="#059669">✓</font>  <b>Matched Skills</b>'
        f'<font color="#6B7280"> — {len(matched)} found in your resume</font>',
        S["h3"]
    ))

    if matched:
        groups = {"core": [], "secondary": [], "bonus": []}
        for sk in matched:
            groups[sk["importance"]].append(sk["name"])

        for imp, lbl, bg_c, bdr_c, txt_c in [
            ("core",      "Core",      SUCCESS_BG, SUCCESS_BDR, SUCCESS),
            ("secondary", "Secondary", INDIGO_DIM, INDIGO_BORDER, INDIGO),
            ("bonus",     "Bonus",     CORAL_DIM,  HexColor("#FDBA9A"), CORAL),
        ]:
            if not groups[imp]:
                continue
            story.append(Paragraph(f"<b>{lbl}</b>", S["clabel"]))
            tbl = _skill_table(groups[imp], bg_c, bdr_c, txt_c)
            if tbl:
                story.append(tbl)
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph(
            "No matching skills found. Ensure your resume uses standard skill names.",
            S["muted"]
        ))

    return story


# ── Page 2: Missing Skills + Recommendations + Next Steps ────────────────────

def _page2(result, role_name, S):
    story = []
    score = result["readiness_score"]

    # ── Missing skills ────────────────────────────────────────────────────────
    missing = result["missing_skills"]
    story.append(Paragraph(
        f'<font color="#DC2626">✗</font>  <b>Missing Skills</b>'
        f'<font color="#6B7280"> — {len(missing)} not in resume · core gaps first</font>',
        S["h3"]
    ))

    if missing:
        groups = {"core": [], "secondary": [], "bonus": []}
        for sk in missing:
            groups[sk["importance"]].append(sk["name"])

        for imp, lbl, bg_c, bdr_c, txt_c in [
            ("core",      "Core  (High Priority)", ERROR_BG, ERROR_BDR, ERROR),
            ("secondary", "Secondary",             WARN_BG,  WARN_BDR,  WARN),
            ("bonus",     "Bonus (Nice to Have)",  SURFACE,  BORDER,    MUTED),
        ]:
            if not groups[imp]:
                continue
            story.append(Paragraph(f"<b>{lbl}</b>", S["clabel"]))
            tbl = _skill_table(groups[imp], bg_c, bdr_c, txt_c)
            if tbl:
                story.append(tbl)
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph(
            "You have all required skills for this role. Excellent!",
            S["ok"]
        ))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=BORDER, spaceAfter=6))

    # ── Recommendations ───────────────────────────────────────────────────────
    recs = result.get("recommendations", [])
    story.append(Paragraph("Alternative Role Matches", S["h2"]))

    if recs:
        # 3 columns side by side
        cells = []
        for rec in recs[:3]:
            sc   = rec["score"]
            rc, rbg, rbdr, rlbl = _sc(sc)
            cell = [
                Paragraph(
                    f'<font color="#{rc.hexval()[2:]}"><b>#{rec["rank"]}</b></font>',
                    ParagraphStyle("rk", fontName="Helvetica-Bold", fontSize=11,
                                   textColor=rc, leading=14, alignment=TA_CENTER)
                ),
                Paragraph(
                    rec["role_name"],
                    ParagraphStyle("rn", fontName="Helvetica-Bold", fontSize=8.5,
                                   textColor=DARK, leading=12, alignment=TA_CENTER,
                                   wordWrap="CJK")
                ),
                Paragraph(
                    f'<font color="#{rc.hexval()[2:]}"><b>{sc:.0f}%</b></font>',
                    ParagraphStyle("rs", fontName="Helvetica-Bold", fontSize=14,
                                   textColor=rc, leading=18, alignment=TA_CENTER)
                ),
                Paragraph(
                    rlbl,
                    ParagraphStyle("rl", fontName="Helvetica", fontSize=7.5,
                                   textColor=MUTED, leading=10, alignment=TA_CENTER)
                ),
            ]
            cells.append(cell)

        # pad to 3 if fewer recs
        while len(cells) < 3:
            cells.append([""])

        rec_tbl = Table([cells], colWidths=[CW / 3] * 3)
        rec_tbl.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.5, BORDER),
            ("INNERGRID",     (0,0),(-1,-1), 0.5, BORDER),
            ("BACKGROUND",    (0,0),(-1,-1), SURFACE),
            ("TOPPADDING",    (0,0),(-1,-1), 10),
            ("BOTTOMPADDING", (0,0),(-1,-1), 10),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
            ("RIGHTPADDING",  (0,0),(-1,-1), 6),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]))
        story.append(rec_tbl)
    else:
        story.append(Paragraph("No alternative recommendations available.", S["muted"]))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=BORDER, spaceAfter=6))

    # ── Next steps ────────────────────────────────────────────────────────────
    story.append(Paragraph("Next Steps", S["h2"]))

    core_missing = [sk for sk in result["missing_skills"]
                    if sk["importance"] == "core"]
    steps = []

    if core_missing:
        names = ", ".join(sk["name"] for sk in core_missing[:4])
        if len(core_missing) > 4:
            names += f" +{len(core_missing) - 4} more"
        steps.append(
            f"<b>Priority — acquire missing core skills:</b> <i>{names}</i>"
        )

    if score >= 70:
        steps.append(
            f"<b>Strong match ({score:.0f}%):</b> You are well-qualified for "
            f"<b>{role_name}</b>. Focus on secondary skills to stand out further."
        )
    elif score >= 40:
        steps.append(
            f"<b>Moderate match ({score:.0f}%):</b> Build your core skills to "
            f"reach 70%+ readiness for <b>{role_name}</b>."
        )
    else:
        steps.append(
            f"<b>Early stage ({score:.0f}%):</b> Consider an adjacent role while "
            f"building skills toward <b>{role_name}</b>."
        )

    steps.append(
        "<b>Update your resume</b> to explicitly name skills as they appear in "
        "job descriptions for better ATS matching."
    )
    steps.append(
        "<b>Re-analyse</b> after upskilling to track your readiness score progress."
    )

    for i, step in enumerate(steps, 1):
        story.append(Paragraph(f"{i}.  {step}", S["step"]))

    # ── Disclaimer ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=BORDER, spaceAfter=6))
    story.append(Paragraph(
        "This report was generated by Smart Resume Analyzer using AI-powered skill "
        "matching. Results are indicative and should be used as a guide alongside "
        "professional career advice.",
        S["disc"]
    ))

    return story


# ── Public API ────────────────────────────────────────────────────────────────

def generate(analysis_id: int, result: dict, user_name: str,
             role_name: str, report_dir: str) -> str:
    """
    Generate a 2-page PDF report.

    Args:
        analysis_id : analyses.id (used for filename)
        result      : dict from analyser.run()
        user_name   : candidate full name
        role_name   : selected job role name
        report_dir  : absolute path to reports/ folder

    Returns:
        Absolute path to saved PDF.
    """
    os.makedirs(report_dir, exist_ok=True)
    filepath = os.path.join(report_dir, f"report_{analysis_id}.pdf")

    doc = SimpleDocTemplate(
        filepath,
        pagesize      = A4,
        leftMargin    = ML,
        rightMargin   = ML,
        topMargin     = MT,
        bottomMargin  = MB,
        title         = f"Resume Analysis — {role_name}",
        author        = "Smart Resume Analyzer",
    )

    S     = _S()
    story = (
        _page1(result, user_name, role_name, S)
        + [PageBreak()]
        + _page2(result, role_name, S)
    )

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return filepath


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dummy = {
        "readiness_score"   : 74.5,
        "predicted_role"    : "Data Analyst",
        "matched_skills"    : [
            {"id":1,  "name":"Python",             "importance":"core"},
            {"id":2,  "name":"Pandas",             "importance":"core"},
            {"id":3,  "name":"NumPy",              "importance":"core"},
            {"id":4,  "name":"Scikit-learn",       "importance":"core"},
            {"id":5,  "name":"Statistics",         "importance":"core"},
            {"id":6,  "name":"Feature Engineering","importance":"core"},
            {"id":7,  "name":"TensorFlow",         "importance":"secondary"},
            {"id":8,  "name":"Jupyter",            "importance":"secondary"},
            {"id":9,  "name":"XGBoost",            "importance":"secondary"},
            {"id":10, "name":"Tableau",            "importance":"bonus"},
        ],
        "missing_skills"    : [
            {"id":11, "name":"Probability",          "importance":"core"},
            {"id":12, "name":"LightGBM",             "importance":"secondary"},
            {"id":13, "name":"Natural Language Processing", "importance":"secondary"},
            {"id":14, "name":"Power BI",             "importance":"bonus"},
            {"id":15, "name":"Apache Spark",         "importance":"bonus"},
        ],
        "core_total"        : 7,
        "core_matched"      : 6,
        "secondary_total"   : 5,
        "secondary_matched" : 3,
        "bonus_total"       : 3,
        "bonus_matched"     : 1,
        "recommendations"   : [
            {"rank":1, "role_id":8,  "role_name":"ML Engineer",   "score":82.1},
            {"rank":2, "role_id":31, "role_name":"Data Analyst",  "score":74.3},
            {"rank":3, "role_id":19, "role_name":"AI Researcher", "score":61.7},
        ],
    }

    out_dir  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
    out_path = generate(99, dummy, "Rahul Sharma", "Data Scientist", out_dir)
    print(f"\nReport saved → {out_path}")