from io import BytesIO
import math
import os
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

# Philippine long bond paper: 8.5 x 13 inches.
PAGE_W, PAGE_H = 612, 936
BLACK = colors.black
MARGIN = 48

def _qr_image(data: str):
    qr = qrcode.QRCode(version=2, box_size=5, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)

def _fit_text(c, text, x, y, max_width, font="Helvetica-Bold", size=14, min_size=8):
    text = str(text or "")
    current = size
    while current > min_size and stringWidth(text, font, current) > max_width:
        current -= 0.5
    c.setFont(font, current)
    c.drawCentredString(x + max_width / 2, y, text)

def _draw_corner_marks(c):
    size, inset = 21, 20
    for x, y in [
        (inset, PAGE_H - inset - size),
        (PAGE_W - inset - size, PAGE_H - inset - size),
        (inset, inset),
        (PAGE_W - inset - size, inset),
    ]:
        c.setFillColor(BLACK)
        c.rect(x, y, size, size, fill=1, stroke=0)

def _title(exam):
    return f"{str(exam.exam_subject).upper()} - {str(exam.exam_title).upper()}"

def _draw_header(c, exam, page_label=None, student_id_mode=None, section_label=None):
    """student_id_mode: None (no id field), "box" (full boxed field — page 1 only),
    or "line" (compact one-line field for every subsequent page, in case a page
    is ever separated from the rest of the student's booklet before scanning)."""
    _draw_corner_marks(c)
    qr = _qr_image(f"ESSCAN|EXAM|{exam.exam_id}")
    qr_size = 38
    c.drawImage(qr, PAGE_W / 2 - qr_size / 2, PAGE_H - 49, qr_size, qr_size, mask="auto")

    c.setFillColor(BLACK)
    c.setFont("Helvetica-Bold", 10)
    if page_label:
        c.drawString(58, PAGE_H - 67, page_label)

    _fit_text(c, _title(exam), 120, PAGE_H - 68, PAGE_W - 240, size=13, min_size=8)

    if section_label:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(58, PAGE_H - 88, section_label.upper())

    base_top = PAGE_H - (102 if section_label else 91)

    if student_id_mode == "box":
        box_x, box_y = 58, PAGE_H - 160
        box_w, box_h = PAGE_W - 116, 70
        c.setLineWidth(2.0)
        c.rect(box_x, box_y, box_w, box_h, fill=0, stroke=1)

        c.setFont("Helvetica-Bold", 11)
        c.drawString(box_x + 10, box_y + 47, "NAME:")
        c.line(box_x + 55, box_y + 46, box_x + 230, box_y + 46)
        c.drawString(box_x + 285, box_y + 47, "STUDENT NO.:")
        c.line(box_x + 375, box_y + 46, box_x + box_w - 12, box_y + 46)
        c.drawString(box_x + 10, box_y + 19, "SECTION:")
        c.line(box_x + 72, box_y + 18, box_x + 230, box_y + 18)

        return box_y - 26

    if student_id_mode == "line":
        # One thin line instead of a full box — just enough to re-identify a
        # stray page by hand, without eating space needed for answers.
        line_y = base_top - 10
        c.setFont("Helvetica-Bold", 8)
        c.drawString(58, line_y, "NAME:")
        c.setLineWidth(0.8)
        c.line(58 + 32, line_y - 2, 58 + 220, line_y - 2)
        c.drawString(58 + 232, line_y, "NO.:")
        c.line(58 + 256, line_y - 2, 58 + 368, line_y - 2)
        c.drawString(58 + 380, line_y, "SEC:")
        c.line(58 + 406, line_y - 2, PAGE_W - 58, line_y - 2)
        return line_y - 18

    return base_top

def _draw_mcq_row(c, x, y, number):
    c.setFillColor(BLACK)
    c.setFont("Helvetica-Bold", 9.8)
    c.drawRightString(x + 27, y - 3.2, f"{number}.")
    start_x, spacing = x + 35, 35
    for i, label in enumerate("ABCDE"):
        cx = start_x + i * spacing
        c.setLineWidth(1.15)
        c.circle(cx, y, 6.3, stroke=1, fill=0)
        c.setFont("Helvetica", 8.8)
        c.drawString(cx + 9, y - 3.0, label)

def _draw_answer_mcq_page(c, exam, numbers, page_no, student_id_mode):
    top = _draw_header(c, exam, f"[ PAGE {page_no} ]", student_id_mode, "ANSWER SHEET")
    sx, sy, sw, bottom = 58, 42, PAGE_W - 116, 42
    sh = top - bottom
    c.setLineWidth(2.0)
    c.rect(sx, sy, sw, sh, fill=0, stroke=1)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(sx + 12, top - 23, "MULTIPLE CHOICE")
    content_top = top - 48
    content_bottom = sy + 18
    rows = math.ceil(len(numbers) / 2)
    gap = min(24.5, (content_top - content_bottom) / max(rows, 1))
    mid = sx + sw / 2 + 6
    for i, n in enumerate(numbers):
        col = 0 if i < math.ceil(len(numbers)/2) else 1
        row = i if col == 0 else i - math.ceil(len(numbers)/2)
        y = content_top - row * gap - 7
        _draw_mcq_row(c, sx + 18 if col == 0 else mid, y, n)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.grey)
    c.drawRightString(sx + sw - 8, sy + 8, "ESSCAN machine-readable answer sheet")

def _draw_essay_answer_page(c, exam, essays, page_no, start_answer, student_id_mode):
    top = _draw_header(c, exam, f"[ PAGE {page_no} ]", student_id_mode, "ANSWER SHEET")
    sx, bottom, sw = 58, 42, PAGE_W - 116
    gap = 14
    count = len(essays)
    # With a maximum of 2 essay answers per page, let each box grow to use the
    # available page height (still capped so a single answer doesn't sprawl).
    box_h = max(95, min(340, (top - bottom - gap * max(0, count-1)) / max(count, 1)))
    for i in range(count):
        y = top - (i + 1) * box_h - i * gap
        c.setLineWidth(2.0)
        c.rect(sx, y, sw, box_h, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(sx + 12, y + box_h - 22, f"[ Answer {start_answer + i} ]")
        c.setFont("Helvetica", 8)
        c.drawRightString(sx + sw - 12, y + box_h - 21, "Write one paragraph")
        c.setLineWidth(0.55)
        first = y + box_h - 45
        lg = 20
        line_count = max(8, int((first - (y + 12)) / lg) + 1)
        for j in range(line_count):
            ly = first - j * lg
            if ly > y + 12:
                c.line(sx + 18, ly, sx + sw - 18, ly)

def _escape(text):
    """Escape text for safe inclusion inside ReportLab Paragraph markup."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

def _question_paragraph(markup, width, font_size=9.2, leading=11.2):
    """Render pre-built (already-escaped) Paragraph markup, e.g. containing <b> tags."""
    style = ParagraphStyle(
        "question",
        fontName="Helvetica",
        fontSize=font_size,
        leading=leading,
        spaceAfter=0,
        textColor=BLACK,
    )
    return Paragraph(markup, style)

class _SectionHeader:
    """Marker item flowed alongside questions to print 'I. MULTIPLE CHOICE' / 'II. ESSAY'."""
    def __init__(self, label):
        self.label = label

def _measure_question_height(q, width):
    """Compute the vertical space an item (header or question) will need, without drawing it."""
    if isinstance(q, _SectionHeader):
        p = _question_paragraph(f"<b>{_escape(q.label)}</b>", width, font_size=11, leading=13.5)
        _, h = p.wrap(width, 500)
        return h + 6

    q_points = float(getattr(q, "points", 0) or 0)
    points_label = f" ({q_points:g} pts)" if q_points > 0 else ""
    q_para = _question_paragraph(f"<b>{q.question_number}. {_escape(q.question_text)}{_escape(points_label)}</b>", width)
    _, h = q_para.wrap(width, 500)
    total = h + 4
    if getattr(q.question_type, "value", q.question_type) == "MCQ":
        options = [q.option_a, q.option_b, q.option_c, q.option_d, q.option_e]
        for option in options:
            p = _question_paragraph(f"X. {_escape(option)}", width - 10, font_size=8.6, leading=10.3)
            _, oh = p.wrap(width - 10, 100)
            total += oh + 1.5
    return total + 9

def _draw_question_block(c, q, x, y_top, width):
    """Draw one questionnaire item (section header or question) and return the next y position."""
    if isinstance(q, _SectionHeader):
        p = _question_paragraph(f"<b>{_escape(q.label)}</b>", width, font_size=11, leading=13.5)
        _, h = p.wrap(width, 500)
        p.drawOn(c, x, y_top - h)
        return y_top - h - 6

    q_points = float(getattr(q, "points", 0) or 0)
    points_label = f" ({q_points:g} pts)" if q_points > 0 else ""
    q_para = _question_paragraph(f"<b>{q.question_number}. {_escape(q.question_text)}{_escape(points_label)}</b>", width)
    w, h = q_para.wrap(width, 500)
    q_para.drawOn(c, x, y_top - h)
    y = y_top - h - 4

    if getattr(q.question_type, "value", q.question_type) == "MCQ":
        options = [q.option_a, q.option_b, q.option_c, q.option_d, q.option_e]
        for letter, option in zip("ABCDE", options):
            p = _question_paragraph(f"{letter}. {_escape(option)}", width - 10, font_size=8.6, leading=10.3)
            _, oh = p.wrap(width - 10, 100)
            p.drawOn(c, x + 9, y - oh)
            y -= oh + 1.5
    return y - 9

def _questionnaire_page(c, exam, questions, page_no):
    _draw_corner_marks(c)
    _fit_text(c, _title(exam), 55, PAGE_H - 55, PAGE_W - 110, size=15, min_size=9)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(PAGE_W/2, PAGE_H - 78, "QUESTIONNAIRE")
    c.setFont("Helvetica", 8)
    c.drawRightString(PAGE_W - 55, PAGE_H - 78, f"Page {page_no}")

    left_x, right_x = 50, PAGE_W/2 + 8
    col_w = PAGE_W/2 - 62
    top = PAGE_H - 105
    bottom = 50

    # Flow items (section headers + questions) sequentially through left column then right column.
    # Measure before drawing so an item that doesn't fit is never drawn twice.
    index = 0
    for col_x in (left_x, right_x):
        y = top
        while index < len(questions):
            item = questions[index]
            needed = _measure_question_height(item, col_w)
            # Keep a section header glued to the question that follows it, so a
            # header never ends up alone at the bottom of a column.
            if isinstance(item, _SectionHeader) and index + 1 < len(questions):
                needed += _measure_question_height(questions[index + 1], col_w)
            if y - needed < bottom and y != top:
                break
            y = _draw_question_block(c, item, col_x, y, col_w)
            index += 1
        c.setStrokeColor(colors.HexColor("#BBBBBB"))
        c.setLineWidth(0.4)
        if col_x == left_x:
            c.line(PAGE_W/2, bottom, PAGE_W/2, top)
    return index

def _essay_questionnaire_page(c, exam, essays, page_no):
    _draw_corner_marks(c)
    _fit_text(c, _title(exam), 55, PAGE_H - 55, PAGE_W - 110, size=15, min_size=9)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(PAGE_W/2, PAGE_H - 78, "QUESTIONNAIRE")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, PAGE_H - 104, "ESSAY")
    y = PAGE_H - 126
    for q in essays:
        q_points = float(getattr(q, "points", 0) or 0)
        points_label = f" ({q_points:g} pts)" if q_points > 0 else ""
        p = _question_paragraph(f"<b>{q.question_number}. {_escape(q.question_text)}{_escape(points_label)}</b>", PAGE_W - 100, font_size=10, leading=13)
        _, h = p.wrap(PAGE_W - 100, 200)
        if y - h < 55:
            c.showPage()
            page_no += 1
            _draw_corner_marks(c)
            _fit_text(c, _title(exam), 55, PAGE_H - 55, PAGE_W - 110, size=15, min_size=9)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(PAGE_W/2, PAGE_H - 78, "QUESTIONNAIRE")
            y = PAGE_H - 105
        p.drawOn(c, 50, y-h)
        y -= h + 14
    return page_no

def build_exam_answer_sheet(exam, db) -> bytes:
    questions = sorted(list(exam.questions), key=lambda q: q.question_number)
    mcqs = [q for q in questions if getattr(q.question_type, "value", q.question_type) == "MCQ"]
    essays = [q for q in questions if getattr(q.question_type, "value", q.question_type) == "Essay"]

    output = BytesIO()
    c = canvas.Canvas(output, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"ESSCAN - {exam.exam_title}")

    # Questionnaire: two columns, no student information. Multiple choice and
    # essay questions are printed as clearly separated, numbered sections.
    questionnaire = []
    if mcqs:
        questionnaire.append(_SectionHeader("I. MULTIPLE CHOICE"))
        questionnaire.extend(mcqs)
    if essays:
        questionnaire.append(_SectionHeader("II. ESSAY" if mcqs else "I. ESSAY"))
        questionnaire.extend(essays)
    if questionnaire:
        remaining = questionnaire
        page_no = 1
        while remaining:
            if page_no > 1:
                c.showPage()
            used = _questionnaire_page(c, exam, remaining, page_no)
            if used <= 0:
                break
            remaining = remaining[used:]
            page_no += 1

        # Ensure essay questions remain easy to read if they were pushed to a page.
        # They are already part of the questionnaire; no separate student fields are added.
        c.showPage()
    else:
        _draw_corner_marks(c)
        _fit_text(c, _title(exam), 55, PAGE_H - 55, PAGE_W - 110, size=15, min_size=9)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(PAGE_W/2, PAGE_H - 78, "QUESTIONNAIRE")
        c.setFont("Helvetica", 10)
        c.drawCentredString(PAGE_W/2, PAGE_H/2, "NO QUESTIONS HAVE BEEN ADDED")
        c.showPage()

    # Answer Sheet Page 1+: MCQ bubbles. The very first physical answer-sheet
    # page gets the full boxed student field; every page after it gets a
    # compact one-line field, so a stray page can still be matched by hand
    # without eating space needed for answers.
    if mcqs:
        for start in range(0, len(mcqs), 60):
            if start > 0:
                c.showPage()
            page_no = 1 + (start // 60)
            _draw_answer_mcq_page(
                c, exam,
                list(range(start + 1, start + min(60, len(mcqs) - start) + 1)),
                page_no,
                student_id_mode=("box" if start == 0 else "line"),
            )
        if essays:
            c.showPage()
    elif essays:
        # No MCQ: page 1 is the essay answer sheet.
        pass

    if essays:
        # Maximum of 2 essay answers per page — additional essay answer pages
        # are created automatically when there are more than 2 essay questions.
        ESSAYS_PER_PAGE = 2
        essay_page_no = (math.ceil(len(mcqs) / 60) + 1) if mcqs else 1
        for start in range(0, len(essays), ESSAYS_PER_PAGE):
            if start > 0:
                c.showPage()
            is_very_first_answer_page = not mcqs and start == 0
            _draw_essay_answer_page(
                c, exam, essays[start:start + ESSAYS_PER_PAGE],
                essay_page_no + start // ESSAYS_PER_PAGE,
                start + 1,
                student_id_mode=("box" if is_very_first_answer_page else "line"),
            )

    c.save()
    output.seek(0)
    return output.read()