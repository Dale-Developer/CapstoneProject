"""
Robust OpenCV OMR for ESSCAN machine-readable answer sheets.

V7.0 alignment strategy:
1. Detect the printed registration squares globally (not only in the image
   corners). Four marks are used directly.
2. If one registration square is outside the camera frame, infer the missing
   corner from the other three. This is useful for real phone photos where a
   page edge may be cropped.
3. If registration marks cannot be recovered, try a document-contour/edge
   fallback.
4. Perspective-warp to the canonical 612x936 answer-sheet coordinate system.
5. Automatically choose the best 0/90/180/270-degree orientation using page
   geometry and horizontal-text/line orientation.
6. Locate bubble circles around the expected positions with Hough circles.
   This compensates for lens distortion and small residual registration error.
   Fixed coordinates remain the final fallback.

The generated PDF is Philippine long bond paper (612 x 936 ReportLab points).
The OMR numbering remains column-first: Q1..Qceil(n/2) in the left column,
then the remaining questions at the top of the right column.
"""
import json
import math
import os
from typing import Any

try:
    import cv2
    import numpy as np
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


# ESSCAN's current generated answer sheet is Philippine long bond paper
# (8.5 x 13 in) at 72 PDF points/inch: 612 x 936.
PAGE_W, PAGE_H = 612.0, 936.0
# exam_pdf.py draws 21pt registration squares with a 20pt inset. OpenCV
# coordinates have their origin at the top-left, so convert the ReportLab
# bottom-left coordinates accordingly.
_MARK_SIZE = 21.0
_MARK_INSET = 20.0
MARK_CENTERS = np.float32([
    # image-space order: top-left, top-right, bottom-left, bottom-right
    [_MARK_INSET + _MARK_SIZE / 2, _MARK_INSET + _MARK_SIZE / 2],
    [PAGE_W - _MARK_INSET - _MARK_SIZE / 2, _MARK_INSET + _MARK_SIZE / 2],
    [_MARK_INSET + _MARK_SIZE / 2, PAGE_H - _MARK_INSET - _MARK_SIZE / 2],
    [PAGE_W - _MARK_INSET - _MARK_SIZE / 2, PAGE_H - _MARK_INSET - _MARK_SIZE / 2],
])

BUBBLE_SPACING = 35.0
BUBBLE_RADIUS = 6.3


def available() -> bool:
    return _AVAILABLE


def _order_points(points):
    """Return four points in image-space TL, TR, BR, BL order."""
    p = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(p) != 4:
        raise ValueError("Exactly four points are required.")
    center = np.mean(p, axis=0)
    angles = np.arctan2(p[:, 1] - center[1], p[:, 0] - center[0])
    cycle = p[np.argsort(angles)]

    # The cyclic order is stable; rotate it so the image-space top-left
    # corner (smallest x+y) becomes the first point.
    start = int(np.argmin(cycle[:, 0] + cycle[:, 1]))
    cycle = np.roll(cycle, -start, axis=0)

    # In image coordinates this cycle is TL, TR, BR, BL for a convex page.
    return cycle.astype(np.float32)


def _registration_candidates(gray):
    """
    Detect square registration marks anywhere on the page/image.

    We deliberately do not restrict this to the four image corners. A phone
    photo can crop one printed corner or place the page at an angle.
    """
    h, w = gray.shape[:2]
    scale = min(1.0, 1400.0 / max(w, h))
    work = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    wh, ww = work.shape[:2]

    # Very dark connected components are effective for the solid printed
    # squares, even when the page has shadows.
    blur = cv2.GaussianBlur(work, (3, 3), 0)
    bw = cv2.threshold(blur, 120, 255, cv2.THRESH_BINARY_INV)[1]
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    image_area = float(ww * wh)

    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < 7 or ch < 7:
            continue
        if cw > ww * 0.12 or ch > wh * 0.12:
            continue
        aspect = cw / max(ch, 1)
        if not 0.60 <= aspect <= 1.67:
            continue
        box_area = float(cw * ch)
        fill = area / max(box_area, 1.0)
        if fill < 0.45:
            continue

        # Registration marks are small relative to the complete page.
        rel = box_area / image_area
        if not 0.00003 <= rel <= 0.012:
            continue

        # Reject very thin text-like components.
        if min(cw, ch) < 0.012 * min(ww, wh):
            continue

        m = cv2.moments(cnt)
        if m["m00"] == 0:
            continue
        cx = m["m10"] / m["m00"]
        cy = m["m01"] / m["m00"]

        # Score square-ness and darkness. QR fragments are usually much
        # smaller and less square as a connected component.
        score = fill * (1.0 - min(abs(1.0 - aspect), 0.8))
        candidates.append((score, area, cx / scale, cy / scale, cw / scale, ch / scale))

    # Non-maximum suppression: keep only one candidate per small neighborhood.
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    kept = []
    min_dist = max(12.0, min(w, h) * 0.012)
    for cand in candidates:
        _, _, cx, cy, cw, ch = cand
        if all((cx-k[0])**2 + (cy-k[1])**2 > min_dist**2 for k in kept):
            kept.append((cx, cy, cw, ch))
        if len(kept) >= 12:
            break

    return kept


def _infer_missing_corner(points):
    """
    Recover a missing page corner from three detected registration marks.

    The three visible marks form three consecutive corners of the page. The
    missing corner is inferred from p_left + p_right - p_opposite. This is
    accurate enough to initialize the perspective transform and is followed
    by canonical-page/bubble refinement.
    """
    p = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(p) != 3:
        return None

    center = p.mean(axis=0)
    angles = np.arctan2(p[:, 1] - center[1], p[:, 0] - center[0])
    cyc = p[np.argsort(angles)]

    # The missing corner lies across the largest angular gap. For three
    # consecutive vertices, the two endpoints of that gap are adjacent to the
    # missing vertex and the remaining point is its opposite.
    ang = np.sort(angles)
    order = np.argsort(angles)
    cyc = p[order]
    gaps = []
    for i in range(3):
        a = angles[order[i]]
        b = angles[order[(i + 1) % 3]]
        gap = (b - a) % (2 * np.pi)
        gaps.append(gap)
    missing_gap = int(np.argmax(gaps))
    a = cyc[missing_gap]
    b = cyc[(missing_gap + 1) % 3]
    opposite = cyc[(missing_gap + 2) % 3]
    missing = a + b - opposite
    return np.vstack([p, missing.astype(np.float32)])


def _select_registration_points(gray):
    """Select the four printed registration marks for live alignment.

    The marks are inset from the physical paper corners, so scoring candidates
    against the image corners can select unrelated square UI/text/QR shapes.
    Instead, choose a convex four-point configuration that best matches the
    known ESSCAN page aspect ratio, has substantial image coverage, and has
    similarly sized dark-square candidates.
    """
    candidates = _registration_candidates(gray)
    if len(candidates) < 3:
        return None, 0, []

    pts = np.float32([[c[0], c[1]] for c in candidates])
    h, w = gray.shape[:2]
    best = None
    import itertools
    max_take = min(len(pts), 12)

    for idxs in itertools.combinations(range(max_take), 4):
        q = pts[list(idxs)]
        try:
            ordered = _order_points(q)
        except Exception:
            continue

        widths = [
            np.linalg.norm(ordered[1] - ordered[0]),
            np.linalg.norm(ordered[2] - ordered[3]),
        ]
        heights = [
            np.linalg.norm(ordered[2] - ordered[1]),
            np.linalg.norm(ordered[3] - ordered[0]),
        ]
        mw, mh = float(np.mean(widths)), float(np.mean(heights))
        if mw < 50 or mh < 50:
            continue

        aspect = mw / max(mh, 1e-6)
        aspect_error = abs(aspect - PAGE_W / PAGE_H)
        area = abs(cv2.contourArea(ordered.reshape(-1, 1, 2)))
        area_ratio = area / max(1.0, w * h)
        if area_ratio < 0.28:
            continue

        sizes = [float(np.mean([candidates[i][2], candidates[i][3]])) for i in idxs]
        mean_size = max(float(np.mean(sizes)), 1.0)
        size_variation = float(np.std(sizes) / mean_size)

        # Prefer page-like geometry and four similarly sized dark squares.
        score = (
            area_ratio * 2.2
            - aspect_error * 2.8
            - size_variation * 1.2
        )
        if best is None or score > best[0]:
            best = (score, ordered)

    if best is not None:
        return best[1], 4, candidates

    # If exactly three marks are visible, infer the missing corner. The final
    # capture path can still use the full document contour as a fallback.
    best_three = None
    for idxs in itertools.combinations(range(min(len(pts), 12)), 3):
        q = pts[list(idxs)]
        area = abs(cv2.contourArea(q.reshape(-1, 1, 2)))
        if best_three is None or area > best_three[0]:
            best_three = (area, q)
    if best_three and best_three[0] > 0:
        inferred = _infer_missing_corner(best_three[1])
        if inferred is not None:
            return _order_points(inferred), 3, candidates

    return None, 0, candidates

def _document_quad_fallback(image):
    """Detect the physical paper boundary as a large quadrilateral.

    This is the primary alignment fallback for camera photos: it does not
    depend on the printed registration squares. Several low/high Canny
    thresholds are tried because room lighting and paper shadows vary.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 1400.0 / max(gray.shape))
    work = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    img_area = float(work.shape[0] * work.shape[1])
    best = None

    for low, high in ((10, 40), (15, 60), (20, 80), (25, 100)):
        blur = cv2.GaussianBlur(work, (5, 5), 0)
        edges = cv2.Canny(blur, low, high)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < img_area * 0.30:
                continue
            peri = cv2.arcLength(cnt, True)
            for eps in (0.02, 0.03, 0.04, 0.05, 0.06):
                approx = cv2.approxPolyDP(cnt, eps * peri, True)
                if len(approx) != 4 or not cv2.isContourConvex(approx):
                    continue
                q = approx.reshape(4, 2).astype(np.float32) / scale
                ordered = _order_points(q)
                w1 = np.linalg.norm(ordered[1] - ordered[0])
                w2 = np.linalg.norm(ordered[2] - ordered[3])
                h1 = np.linalg.norm(ordered[2] - ordered[1])
                h2 = np.linalg.norm(ordered[3] - ordered[0])
                mw, mh = (w1 + w2) / 2, (h1 + h2) / 2
                ratio = min(mw, mh) / max(mw, mh)
                if not 0.45 <= ratio <= 0.82:
                    continue
                ratio_error = abs(ratio - 612 / 936)
                score = area * (1.0 - min(ratio_error * 2.0, 0.75))
                if best is None or score > best[0]:
                    best = (score, ordered, area / img_area)

    if best:
        return best[1], "document_contour", float(best[2])
    return None, None, 0.0


def _bubble_match_score(gray_or_image, question_count: int):
    """Score an orientation by how many expected bubble circles are found."""
    if question_count <= 0:
        return 0

    if len(gray_or_image.shape) == 3:
        gray = cv2.cvtColor(gray_or_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = gray_or_image

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=10,
        param1=70,
        param2=12,
        minRadius=3,
        maxRadius=9,
    )
    if circles is None:
        return 0

    detected = np.round(circles[0]).astype(int)
    expected = _bubble_positions(question_count)
    used = set()
    matches = 0

    for _, ex, ey, _ in expected:
        best = None
        for i, (cx, cy, _) in enumerate(detected):
            if i in used:
                continue
            distance = math.hypot(float(cx-ex), float(cy-ey))
            if distance <= 14.0 and (best is None or distance < best[0]):
                best = (distance, i)
        if best:
            used.add(best[1])
            matches += 1

    return matches


def _orientation_candidates(image, points, method, question_count):
    """Create canonical-page candidates for the two possible 90-degree directions."""
    points = _order_points(points)
    tl, tr, br, bl = points

    edge_width = (np.linalg.norm(tr-tl) + np.linalg.norm(br-bl)) / 2.0
    edge_height = (np.linalg.norm(bl-tl) + np.linalg.norm(br-tr)) / 2.0

    if method == "document_contour":
        # Physical page boundary maps to the physical page boundary.
        x0, y0, x1, y1 = 0.0, 0.0, PAGE_W - 1.0, PAGE_H - 1.0
        portrait = np.float32([[x0,y0],[x1,y0],[x1,y1],[x0,y1]])
        cw = np.float32([[x1,y0],[x1,y1],[x0,y1],[x0,y0]])
        ccw = np.float32([[x0,y1],[x0,y0],[x1,y0],[x1,y1]])
        half = np.float32([[x1,y1],[x0,y1],[x0,y0],[x1,y0]])
        targets = [("0", portrait), ("90_cw", cw), ("90_ccw", ccw), ("180", half)]
    else:
        # Registration squares map to the actual canonical centers used by
        # backend/services/exam_pdf.py.
        tl, tr, bl, br = MARK_CENTERS[0], MARK_CENTERS[1], MARK_CENTERS[2], MARK_CENTERS[3]
        targets = [
            ("0", np.float32([tl, tr, br, bl])),
            ("90_cw", np.float32([tr, br, bl, tl])),
            ("90_ccw", np.float32([bl, tl, tr, br])),
            ("180", np.float32([br, bl, tl, tr])),
        ]

    candidates = []
    for orientation, dst in targets:
        matrix = cv2.getPerspectiveTransform(points, dst)
        warped = cv2.warpPerspective(
            image, matrix, (int(PAGE_W), int(PAGE_H)),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        bubble_score = _bubble_match_score(warped, question_count)
        candidates.append((bubble_score, orientation, warped))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def _bubble_positions(question_count: int):
    """Return bubble centers matching the current backend exam_pdf.py.

    The generated ESSCAN MCQ page uses 612x936 long bond paper, two columns,
    35pt option spacing, and a dynamic row gap so the available question rows
    fill the page. PDF coordinates are converted to OpenCV top-left coordinates.
    """
    if question_count <= 0:
        return []

    sx, sy, sw, bottom = 58.0, 42.0, PAGE_W - 116.0, 42.0
    # Page 1 is the student-ID boxed page. _draw_header() returns 750pt
    # after placing the 70pt student-information box. The current upload
    # flow processes Page 1 for the supported MCQ layout.
    top = PAGE_H - 186.0
    content_top = top - 48.0
    content_bottom = sy + 18.0
    rows = math.ceil(question_count / 2)
    gap = min(24.5, (content_top - content_bottom) / max(rows, 1))
    mid = sx + sw / 2.0 + 6.0
    split = math.ceil(question_count / 2)

    out = []
    for i in range(question_count):
        col = 0 if i < split else 1
        row = i if col == 0 else i - split
        base_x = sx + 18.0 if col == 0 else mid
        row_y_pdf = content_top - row * gap - 7.0
        for option_index, option in enumerate("ABCDE"):
            center_x = base_x + 35.0 + option_index * 35.0
            center_y = PAGE_H - row_y_pdf
            out.append((i, center_x, center_y, option))
    return out


def _detect_bubble_centers(gray, expected):
    """
    Find actual printed bubble circles near the expected positions.

    This compensates for residual lens distortion, small perspective errors,
    and camera photos that are not perfectly planar. Expected positions are
    still used as a strong prior, so text and unrelated circles are ignored.
    """
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=10,
        param1=70,
        param2=12,
        minRadius=3,
        maxRadius=9,
    )
    if circles is None:
        return {}

    detected = np.round(circles[0]).astype(int)
    used = set()
    mapping = {}

    for q_index, ex, ey, option in expected:
        candidates = []
        for i, (cx, cy, r) in enumerate(detected):
            if i in used:
                continue
            dist = math.hypot(float(cx-ex), float(cy-ey))
            if dist <= 14.0:
                candidates.append((dist, i, int(cx), int(cy), int(r)))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            dist, idx, cx, cy, radius = candidates[0]
            used.add(idx)
            mapping[(q_index, option)] = {
                "x": cx, "y": cy, "radius": radius, "distance": round(dist, 2)
            }

    return mapping


def _bubble_fill_metrics(gray, x, y, radius=4.0):
    """Measure bubble shading using both grayscale darkness and local Otsu fill."""
    outer_radius = max(4, int(round(radius * 1.45)))
    inner_radius = max(2, int(round(radius * 0.72)))
    x0 = max(0, int(round(x)) - outer_radius)
    x1 = min(gray.shape[1], int(round(x)) + outer_radius + 1)
    y0 = max(0, int(round(y)) - outer_radius)
    y1 = min(gray.shape[0], int(round(y)) + outer_radius + 1)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0, 0.0

    cx = int(round(x)) - x0
    cy = int(round(y)) - y0
    yy, xx = np.ogrid[:patch.shape[0], :patch.shape[1]]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= inner_radius ** 2
    values = patch[mask]
    if values.size == 0:
        return 0.0, 0.0

    darkness = 1.0 - float(np.mean(values)) / 255.0
    blurred = cv2.GaussianBlur(patch, (3, 3), 0)
    _, binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    dark_ratio = float(np.mean(binary[mask] > 0))
    percentile_darkness = 1.0 - float(np.percentile(values, 65)) / 255.0

    fill = max(
        0.0,
        min(1.0, darkness * 0.50 + dark_ratio * 0.35 + percentile_darkness * 0.15),
    )
    return fill, darkness


def _dark_ratio(gray, x, y, radius=3.8):
    fill, _ = _bubble_fill_metrics(gray, x, y, radius)
    return fill


def _bubble_darkness(gray, x, y):
    _, darkness = _bubble_fill_metrics(gray, x, y, 4.0)
    return darkness




def _quad_geometry(points):
    """Return lightweight page-geometry metrics used to reject bad captures."""
    try:
        p = _order_points(points)
        tl, tr, br, bl = p
        top_vec = tr - tl
        bottom_vec = br - bl
        left_vec = bl - tl
        right_vec = br - tr

        top_angle = math.degrees(math.atan2(float(top_vec[1]), float(top_vec[0])))
        bottom_angle = math.degrees(math.atan2(float(bottom_vec[1]), float(bottom_vec[0])))

        # Normalize rotation to the nearest horizontal angle.
        def horizontal_deviation(angle):
            angle = ((angle + 90.0) % 180.0) - 90.0
            return abs(angle)

        def corner_angle(a, b):
            denom = (np.linalg.norm(a) * np.linalg.norm(b))
            if denom <= 1e-6:
                return 0.0
            cosine = float(np.dot(a, b) / denom)
            cosine = max(-1.0, min(1.0, cosine))
            return math.degrees(math.acos(cosine))

        angles = [
            corner_angle(tr - tl, bl - tl),
            corner_angle(tl - tr, br - tr),
            corner_angle(br - bl, tr - br),
            corner_angle(bl - br, tl - bl),
        ]
        width = (np.linalg.norm(top_vec) + np.linalg.norm(bottom_vec)) / 2.0
        height = (np.linalg.norm(left_vec) + np.linalg.norm(right_vec)) / 2.0
        aspect = width / max(height, 1e-6)
        corner_error = float(np.mean([abs(a - 90.0) for a in angles]))
        skew = (horizontal_deviation(top_angle) + horizontal_deviation(bottom_angle)) / 2.0

        return {
            "width": round(float(width), 2),
            "height": round(float(height), 2),
            "aspect_ratio": round(float(aspect), 4),
            "skew_degrees": round(float(skew), 2),
            "corner_error_degrees": round(corner_error, 2),
            "area": round(float(abs(cv2.contourArea(p.reshape(-1, 1, 2)))), 2),
        }
    except Exception:
        return {
            "width": 0.0, "height": 0.0, "aspect_ratio": 0.0,
            "skew_degrees": 90.0, "corner_error_degrees": 90.0, "area": 0.0,
        }


def _quick_alignment(image):
    """Fast live-preview detector: low resolution, no perspective warp/Hough.

    The final uploaded image still goes through the full robust alignment
    pipeline. This endpoint is intentionally cheap so a phone does not send
    a CPU-heavy OpenCV job every frame.
    """
    if image is None or image.size == 0:
        return None, 0, [], 0.0

    h, w = image.shape[:2]
    scale = min(1.0, 900.0 / max(w, h))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    points, marker_count, marker_candidates = _select_registration_points(gray)
    method = "registration_marks" if points is not None else None

    if points is None:
        points, method, area_ratio = _document_quad_fallback(small)
        if points is None:
            return None, 0, [], 0.0
    else:
        area_ratio = 0.0

    geometry = _quad_geometry(points)
    # Penalize implausible paper geometry, severe skew, and perspective.
    aspect_error = abs(geometry["aspect_ratio"] - PAGE_W / PAGE_H)
    aspect_score = max(0.0, 1.0 - aspect_error / 0.22)
    skew_score = max(0.0, 1.0 - geometry["skew_degrees"] / 22.0)
    corner_score = max(0.0, 1.0 - geometry["corner_error_degrees"] / 28.0)

    if method == "registration_marks":
        base_score = 0.90 if marker_count >= 4 else 0.82
    else:
        base_score = 0.80 if area_ratio >= 0.38 else 0.70

    confidence = max(
        0.0,
        min(0.99, base_score * 0.55 + aspect_score * 0.20 + skew_score * 0.15 + corner_score * 0.10),
    )
    return points, marker_count, geometry, confidence


def _warp(image, question_count=0):
    """Automatically detect the sheet and orient it for processing.

    The camera user never has to manually align four squares. We try the
    physical paper boundary and the printed registration marks automatically,
    then choose the candidate that best explains the expected OMR layout.

    PERFORMANCE NOTE: candidate detection and every orientation trial below
    used to run at the phone's full camera resolution (often 3000-4000px on
    the long edge), even though only the four corner points are ever used
    downstream — scanner.prepare_scan() discards the warped preview this
    function builds and redoes the perspective transform itself at full
    resolution using just the returned corner coordinates. So this function
    now detects on a capped-resolution copy of the image (SCANNER_DETECTION_
    MAX_DIM, default 1800px) and scales the winning corner points back up to
    the original image's coordinate space before returning. Final OCR/OMR
    image quality is unaffected; only the (previously wasted) cost of corner
    detection and orientation scoring at full resolution goes away.

    This has one real constraint worth knowing if you change the default:
    _select_registration_points() rejects any candidate mark smaller than
    50px in whichever resolution it is evaluating, so SCANNER_DETECTION_MAX_
    DIM must stay high enough that the printed registration squares are
    still comfortably above that floor. 1800px has a wide safety margin for
    normal phone-camera photos; lower it only if you have verified detection
    still succeeds on your actual answer sheets, and set it to 0 to disable
    downscaling entirely and restore the original full-resolution behavior.
    """
    detect_scale = 1.0
    max_dim = _env_int("SCANNER_DETECTION_MAX_DIM", 1800, 0, 6000)
    if max_dim > 0:
        h0, w0 = image.shape[:2]
        longest_edge = max(h0, w0)
        if longest_edge > max_dim:
            detect_scale = max_dim / float(longest_edge)
            image = cv2.resize(
                image,
                (max(1, int(round(w0 * detect_scale))), max(1, int(round(h0 * detect_scale)))),
                interpolation=cv2.INTER_AREA,
            )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    candidates_to_try = []

    # Candidate A: actual paper/document boundary.
    doc_points, doc_method, doc_area_ratio = _document_quad_fallback(image)
    if doc_points is not None:
        candidates_to_try.append((doc_points, doc_method, 0, [], doc_area_ratio))

    # Candidate B: printed registration marks. These are detected automatically
    # from the image; the user is not asked to line them up.
    mark_points, marker_count, marker_candidates = _select_registration_points(gray)
    if mark_points is not None:
        candidates_to_try.append((mark_points, "registration_marks", marker_count, marker_candidates, 0.0))

    if not candidates_to_try:
        h, w = image.shape[:2]
        if h > w * 1.12 and h >= 450:
            warped = cv2.resize(image, (int(PAGE_W), int(PAGE_H)), interpolation=cv2.INTER_AREA)
            return warped, False, None, {
                "alignment_method": "portrait_scale_fallback",
                "document_area_ratio": 0.0,
                "marker_count": 0,
                "orientation": "0",
                "orientation_score": 0.45,
                "bubble_layout_matches": _bubble_match_score(warped, question_count),
                "confidence": 0.45,
            }
        raise ValueError("Automatic page detection failed. Keep the entire answer sheet visible and try again.")

    evaluated = []
    for points, method, marker_count, marker_candidates, area_ratio in candidates_to_try:
        for bubble_score, orientation, warped in _orientation_candidates(image, points, method, question_count):
            evaluated.append((bubble_score, method, orientation, warped, points, marker_count, marker_candidates, area_ratio))

    # For MCQ pages, bubble geometry is the strongest proof that the detected
    # quadrilateral is the actual answer sheet. For essay pages, prefer an
    # automatically detected registration-mark transform when available.
    if question_count > 0:
        evaluated.sort(key=lambda x: (x[0], 1 if x[1] == "registration_marks" else 0), reverse=True)
    else:
        evaluated.sort(key=lambda x: (1 if x[1] == "registration_marks" else 0, x[7]), reverse=True)

    best_score, method, orientation, warped, points, marker_count, marker_candidates, area_ratio = evaluated[0]

    # Corner points were found in the (possibly downscaled) detection copy;
    # map them back to the original full-resolution image before returning,
    # so the caller's high-resolution perspective warp lands in the right
    # place. `warped` itself is left at detection resolution — callers that
    # care about output quality (scanner.prepare_scan) redo the warp
    # themselves at full resolution using these corner points, not `warped`.
    if detect_scale != 1.0:
        points = points / detect_scale
    expected_count = max(1, question_count * 5)
    layout_confidence = best_score / expected_count

    if question_count > 0 and best_score < max(5, int(expected_count * 0.20)):
        raise ValueError(
            "The page was detected, but its orientation could not be verified against the MCQ bubble layout. Retake the photo with the whole answer sheet visible."
        )

    confidence = (
        0.95 if method == "registration_marks" and marker_count >= 4 else
        0.84 if method == "registration_marks" and marker_count == 3 else
        0.92 if method == "document_contour" and area_ratio >= 0.38 else
        0.84 if method == "document_contour" else
        0.45
    )
    if question_count > 0:
        confidence = min(0.99, confidence + 0.04 * min(layout_confidence, 1.0))

    return warped, True, points.tolist(), {
        "alignment_method": method,
        "document_area_ratio": round(float(area_ratio), 4),
        "marker_count": marker_count,
        "marker_candidates": len(marker_candidates),
        "orientation": orientation,
        "bubble_layout_matches": int(best_score),
        "bubble_layout_expected": int(expected_count),
        "confidence": round(confidence, 4),
        "automatic_detection": True,
    }

def analyze_page(
    image_bytes: bytes,
    question_numbers: list[int],
    fill_threshold: float = 0.24,
    ambiguity_margin: float = 0.055,
    already_aligned: bool = False,
) -> dict[str, Any]:
    """
    Analyze one physical MCQ answer-sheet page.

    The returned result includes every option measurement, alignment method,
    marker count, orientation, and bubble-center diagnostics so the complete
    processing decision can be stored in the database.
    """
    if not _AVAILABLE:
        return {"available": False, "error": "opencv-python-headless is not installed."}

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return {"available": True, "error": "Unable to decode the page image."}

    try:
        if already_aligned:
            warped = image
            registered = True
            source_corners = None
            alignment = {
                "alignment_method": "scanner_master",
                "confidence": 0.99,
                "automatic_detection": True,
            }
        else:
            warped, registered, source_corners, alignment = _warp(image, len(question_numbers))
    except Exception as exc:
        return {
            "available": True,
            "error": str(exc),
            "alignment": {
                "alignment_method": "failed",
                "confidence": 0.0,
            },
        }

    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    expected = _bubble_positions(len(question_numbers))
    detected_centers = _detect_bubble_centers(gray, expected)

    per_question = {}
    for q_index, x, y, option in expected:
        qnum = question_numbers[q_index]
        per_question.setdefault(qnum, {})

        detected = detected_centers.get((q_index, option))
        if detected:
            cx, cy = detected["x"], detected["y"]
            center_source = "hough"
            center_offset = detected["distance"]
        else:
            cx, cy = x, y
            center_source = "expected"
            center_offset = None

        ratio = _dark_ratio(gray, cx, cy)
        darkness = _bubble_darkness(gray, cx, cy)
        per_question[qnum][option] = {
            "fill_ratio": round(ratio, 4),
            "darkness": round(darkness, 4),
            "center_x": round(float(cx), 2),
            "center_y": round(float(cy), 2),
            "center_source": center_source,
            "center_offset": center_offset,
        }

    answers = []
    for qnum in question_numbers:
        options = per_question[qnum]
        ranked = sorted(
            options.items(),
            key=lambda kv: kv[1]["fill_ratio"],
            reverse=True,
        )
        best_option, best = ranked[0]
        second_ratio = ranked[1][1]["fill_ratio"] if len(ranked) > 1 else 0.0
        is_blank = best["fill_ratio"] < fill_threshold
        is_ambiguous = (
            (not is_blank)
            and (best["fill_ratio"] - second_ratio < ambiguity_margin)
        )

        answers.append({
            "question_number": qnum,
            "selected_option": None if is_blank or is_ambiguous else best_option,
            "is_blank": bool(is_blank),
            "is_ambiguous": bool(is_ambiguous),
            "confidence": round(
                max(0.0, min(1.0, best["fill_ratio"])),
                4,
            ),
            "best_fill_ratio": round(best["fill_ratio"], 4),
            "second_fill_ratio": round(second_ratio, 4),
            "options": options,
        })

    return {
        "available": True,
        "registered": registered,
        "source_corners": np.asarray(source_corners).tolist() if source_corners is not None else None,
        "normalized_size": [int(PAGE_W), int(PAGE_H)],
        "alignment": alignment,
        "bubble_detection": {
            "method": "hough_near_expected",
            "expected_bubbles": len(expected),
            "detected_bubbles": len(detected_centers),
        },
        "fill_threshold": fill_threshold,
        "ambiguity_margin": ambiguity_margin,
        "numbering": "column_first",
        "answers": answers,
        "raw_json": json.dumps(answers, ensure_ascii=False),
    }



def rectify_page_for_ocr(image):
    """Return a canonical 612x936 answer-sheet image for OCR crops.

    This is an internal helper for the hybrid OCR pipeline. It reuses the
    existing OpenCV page registration/orientation logic and does not alter
    the frontend or the public OMR API.
    """
    if not _AVAILABLE:
        return None
    try:
        _warped, registered, _source_corners, _alignment = _warp(image, question_count=0)
        if _warped is None:
            return None
        return _warped
    except Exception:
        return None

def detect_page_alignment(image_bytes: bytes, question_count: int = 0) -> dict[str, Any]:
    """Fast live-camera readiness check.

    Only low-resolution geometry is evaluated here. The final captured image
    is processed by the full perspective/OMR pipeline, so preview requests
    stay lightweight while the final result remains accurate.
    """
    if not _AVAILABLE:
        return {"available": False, "ready": False, "error": "OpenCV is not installed."}

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return {"available": True, "ready": False, "error": "Unable to decode camera frame."}

    try:
        points, marker_count, geometry, confidence = _quick_alignment(image)
        if points is None:
            return {
                "available": True, "ready": False,
                "error": "Keep the entire page visible.",
                "alignment": {"alignment_method": "not_detected", "confidence": 0.0},
            }

        method = "registration_marks" if marker_count >= 3 else "document_contour"
        # Capture only when the page is sufficiently flat/straight and fills
        # a reasonable portion of the frame. Perspective correction handles
        # the remaining small skew in the final upload.
        ready = (
            confidence >= 0.79
            and geometry["aspect_ratio"] >= 0.50
            and geometry["aspect_ratio"] <= 0.75
            and geometry["skew_degrees"] <= 14.0
            and geometry["corner_error_degrees"] <= 22.0
        )
        return {
            "available": True,
            "ready": bool(ready),
            "registered": marker_count >= 3,
            "alignment": {
                "alignment_method": method,
                "marker_count": marker_count,
                "confidence": round(confidence, 4),
                **geometry,
                "automatic_detection": True,
            },
            "source_corners": np.asarray(points).tolist(),
        }
    except Exception as exc:
        return {
            "available": True, "ready": False, "error": str(exc),
            "alignment": {"alignment_method": "failed", "confidence": 0.0},
        }

