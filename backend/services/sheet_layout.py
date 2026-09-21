"""Canonical ESSCAN answer-sheet geometry.

Every coordinate that describes where something is printed on an answer sheet
lives here, and both sides of the pipeline import it:

    exam_pdf.py      -- draws boxes, labels and guide lines at these positions
    ocr_hybrid.py    -- crops those same regions back out of a scanned photo

Before this module existed the two files each carried their own copy of the
numbers, and they had silently drifted apart: the PDF drew every answer box at
the same full-page rectangle while the OCR cropper assumed they were stacked,
and the OCR crop began one ruled line below where writing actually starts. A
scanned sheet therefore lost its first line and, on two-answer pages, split one
student's answer across two questions.

All values are in ReportLab points, with the origin at the BOTTOM-LEFT of the
page, matching ReportLab's own coordinate system. ``essay_crop_box`` is the one
function that converts to top-left image coordinates, because that is what
OpenCV and PIL want.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
PAGE_W = 612.0
PAGE_H = 936.0

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
# Vertical start of the content area, measured down from the top of the page.
# The larger inset applies when a section label ("ANSWER SHEET") is printed.
HEADER_BASE_INSET = 102.0
HEADER_BASE_INSET_NO_SECTION = 91.0

# Full boxed student-ID field (first physical answer-sheet page only).
ID_BOX_X = 58.0
ID_BOX_Y = PAGE_H - 160.0          # 776
ID_BOX_W = PAGE_W - 116.0          # 496
ID_BOX_H = 70.0
ID_BOX_GAP_BELOW = 26.0

# Compact one-line student-ID field (every page after the first).
ID_LINE_GAP_ABOVE = 10.0
ID_LINE_GAP_BELOW = 18.0

# ---------------------------------------------------------------------------
# Essay answer boxes
# ---------------------------------------------------------------------------
ESSAY_X = 58.0                     # left edge of the printed border
ESSAY_W = PAGE_W - 116.0           # 496
ESSAY_BOTTOM = 42.0                # lowest printed pixel on the page
ESSAY_GAP = 14.0                   # vertical gap between stacked answer boxes

LABEL_INSET_TOP = 22.0             # "[ Answer N ]" baseline, below the box top
GUIDE_INSET_TOP = 45.0             # first handwriting guide line, below box top
GUIDE_INSET_BOTTOM = 12.0          # guide lines stop this far above the box floor
GUIDE_LINE_SPACING = 20.0
GUIDE_INSET_X = 18.0               # guide lines are inset this far from the border

# The OCR crop deliberately does NOT match the guide lines exactly.
#
# Vertically: handwriting SITS ON a ruled line and extends upward from it, so a
# crop whose ceiling is the first guide line cuts that entire line off. The
# ceiling is raised to 26pt below the box top -- 19pt of headroom above the
# first line, still 4pt clear of the "[ Answer N ]" label baseline at 22pt.
#
# Horizontally: students overshoot the ends of the ruled lines, so the crop
# runs wider than the guides, stopping 10pt short of the printed border so the
# 2pt border stroke is never detected as a character.
CROP_INSET_TOP = 26.0
CROP_INSET_BOTTOM = 6.0
CROP_INSET_X = 10.0

MAX_ESSAYS_PER_PAGE = 2

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
# Which ``expected_response_format`` values are given a page to themselves.
# Everything else is a short answer and may share a page, up to
# ``MAX_ESSAYS_PER_PAGE``.
LONG_RESPONSE_FORMATS = frozenset({"multi_paragraph", "essay"})


def is_long_format(response_format: str | None) -> bool:
    return str(response_format or "one_paragraph") in LONG_RESPONSE_FORMATS


def plan_essay_pages(response_formats) -> list[list[int]]:
    """Group essay questions into printed pages.

    Takes the ``expected_response_format`` of each essay question, in question
    order, and returns one list per printed page holding the indices of the
    questions on it. Page 0 is the first essay page.

    This is the third piece of answer-sheet knowledge to become shared, for
    the same reason as the first two: ``exam_pdf`` decides the pagination when
    it prints, and ``submission_pipeline`` has to reconstruct exactly the same
    decision when it reads the scan back. It previously re-derived it with
    ``page_index * 2 + box_index``, which is only correct when every question
    is a short answer. One ``multi_paragraph`` question in the middle of an
    exam shifts every later answer onto the wrong question, and silently: the
    text is real, the grade is real, and it belongs to a different question.
    """
    pages: list[list[int]] = []
    current: list[int] = []

    for index, response_format in enumerate(response_formats):
        if is_long_format(response_format):
            # Flush any short answers waiting for a page-mate first, so the
            # long answer starts on a clean page.
            if current:
                pages.append(current)
                current = []
            pages.append([index])
        else:
            current.append(index)
            if len(current) == MAX_ESSAYS_PER_PAGE:
                pages.append(current)
                current = []

    if current:
        pages.append(current)
    return pages


def header_base_top(has_section_label: bool = True) -> float:
    """Y of the content area before any student-ID field is drawn."""
    inset = HEADER_BASE_INSET if has_section_label else HEADER_BASE_INSET_NO_SECTION
    return PAGE_H - inset


def content_top(student_id_mode: str | None, has_section_label: bool = True) -> float:
    """Y below which an answer area may start, for a given header style.

    ``student_id_mode`` mirrors ``exam_pdf._draw_header``: ``"box"`` for the
    full boxed NAME/NO./SECTION field, ``"line"`` for the compact one-line
    version, ``None`` for no ID field at all.
    """
    if student_id_mode == "box":
        return ID_BOX_Y - ID_BOX_GAP_BELOW                       # 750
    base = header_base_top(has_section_label)
    if student_id_mode == "line":
        return base - ID_LINE_GAP_ABOVE - ID_LINE_GAP_BELOW      # 806
    return base


def essay_student_id_mode(has_mcq: bool, essay_page_index: int) -> str:
    """Which ID field ``exam_pdf`` prints on a given essay page.

    Only the very first physical answer-sheet page carries the full box. When
    the exam has multiple-choice questions that first page is an MCQ page, so
    every essay page gets the compact line instead.

    Getting this wrong is a 56pt vertical error -- roughly three lines of
    handwriting -- which is exactly the bug this function exists to prevent.
    """
    return "box" if (not has_mcq and essay_page_index == 0) else "line"


def essay_content_top(has_mcq: bool, essay_page_index: int) -> float:
    return content_top(essay_student_id_mode(has_mcq, essay_page_index))


def essay_box_height(top: float, count: int) -> float:
    """Height of one answer box when ``count`` boxes share the page."""
    count = max(1, min(MAX_ESSAYS_PER_PAGE, int(count or 1)))
    usable = top - ESSAY_BOTTOM - ESSAY_GAP * (count - 1)
    return usable / count


def essay_box(top: float, count: int, index: int) -> tuple[float, float, float, float]:
    """The printed rectangle for answer ``index``, as (x, y, width, height).

    Boxes are stacked top-down: index 0 is the topmost. ``y`` is the bottom
    edge, per ReportLab.
    """
    box_h = essay_box_height(top, count)
    y = top - (index + 1) * box_h - index * ESSAY_GAP
    return ESSAY_X, y, ESSAY_W, box_h


def guide_lines(box_y: float, box_h: float) -> list[float]:
    """Y positions of the printed handwriting guide lines, top-down."""
    first = box_y + box_h - GUIDE_INSET_TOP
    floor = box_y + GUIDE_INSET_BOTTOM
    lines = []
    y = first
    while y > floor:
        lines.append(y)
        y -= GUIDE_LINE_SPACING
    return lines


def essay_crop_box(
    top: float,
    count: int,
    index: int,
    page_w: int,
    page_h: int,
) -> tuple[int, int, int, int]:
    """Pixel crop for answer ``index`` on a normalized page image.

    Returns ``(x1, y1, x2, y2)`` in TOP-LEFT image coordinates, ready to hand
    to ``PIL.Image.crop`` or to slice a numpy array. ``page_w``/``page_h`` are
    the pixel dimensions of the rectified page, whatever scale it was warped
    to.
    """
    _, box_y, _, box_h = essay_box(top, count, index)

    left = ESSAY_X + CROP_INSET_X
    right = ESSAY_X + ESSAY_W - CROP_INSET_X
    upper = box_y + box_h - CROP_INSET_TOP     # PDF coords: higher y = higher up
    lower = box_y + CROP_INSET_BOTTOM

    sx = page_w / PAGE_W
    sy = page_h / PAGE_H

    x1 = max(0, int(left * sx))
    x2 = min(page_w, int(right * sx))
    # Flip the vertical axis: PDF measures up from the bottom, images down
    # from the top.
    y1 = max(0, int((PAGE_H - upper) * sy))
    y2 = min(page_h, int((PAGE_H - lower) * sy))
    return x1, y1, x2, y2


def id_field_crop_box(page_w: int, page_h: int, margin: float = 10.0) -> tuple[int, int, int, int]:
    """Pixel crop around the boxed NAME / STUDENT NO. / SECTION field.

    Cropping the ID box itself rather than a percentage of the page keeps the
    QR code, the exam title and the page label out of the image entirely, so
    the recognizer sees only handwriting and three short printed labels.
    """
    left = ID_BOX_X - margin
    right = ID_BOX_X + ID_BOX_W + margin
    upper = ID_BOX_Y + ID_BOX_H + margin
    lower = ID_BOX_Y - margin

    sx = page_w / PAGE_W
    sy = page_h / PAGE_H

    x1 = max(0, int(left * sx))
    x2 = min(page_w, int(right * sx))
    y1 = max(0, int((PAGE_H - upper) * sy))
    y2 = min(page_h, int((PAGE_H - lower) * sy))
    return x1, y1, x2, y2


__all__ = [
    "PAGE_W", "PAGE_H", "ESSAY_X", "ESSAY_W", "ESSAY_BOTTOM", "ESSAY_GAP",
    "LABEL_INSET_TOP", "GUIDE_INSET_TOP", "GUIDE_INSET_BOTTOM",
    "GUIDE_LINE_SPACING", "GUIDE_INSET_X", "MAX_ESSAYS_PER_PAGE",
    "LONG_RESPONSE_FORMATS", "is_long_format", "plan_essay_pages",
    "header_base_top", "content_top", "essay_student_id_mode",
    "essay_content_top", "essay_box_height", "essay_box", "guide_lines",
    "essay_crop_box", "id_field_crop_box",
]
