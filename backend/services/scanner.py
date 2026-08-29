"""ESSCAN V7.4 smart document scanner and AI image preparation.

The scanner's job is to create one high-quality, geometrically normalized
master image from a phone photo. Downstream modules then use purpose-specific
views of that master:

- OpenCV: canonical 612x936 grayscale page for OMR.
- EasyOCR: high-resolution RGB/CLAHE page preserving handwriting strokes.
- Qwen2.5-VL 3B: clean RGB page, compressed only after normalization.

The original upload is never destroyed. The normalized master is used for AI
processing so camera perspective, rotation, and uneven framing do not leak
into the OCR/OMR stages.
"""
from __future__ import annotations

import io
import math
import os
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from services import omr


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def decode_image(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return image


def _jpeg_bytes(image: np.ndarray, quality: int = 94) -> bytes:
    quality = max(70, min(98, int(quality)))
    ok, encoded = cv2.imencode(
        ".jpg", image,
        [int(cv2.IMWRITE_JPEG_QUALITY), quality,
         int(cv2.IMWRITE_JPEG_OPTIMIZE), 1],
    )
    if not ok:
        raise ValueError("Unable to encode normalized scan.")
    return encoded.tobytes()


def _quality_metrics(image: np.ndarray, page_points=None) -> dict[str, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(lap.var())
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    clipped_dark = float(np.mean(gray <= 8))
    clipped_light = float(np.mean(gray >= 247))

    # A simple glare indicator: bright pixels with low local variation are
    # usually paper/lighting, while bright high-frequency regions are less
    # likely to be a washed-out highlight.
    glare = float(np.mean(gray >= 250))

    area_ratio = 0.0
    if page_points is not None:
        try:
            area = abs(cv2.contourArea(np.asarray(page_points, dtype=np.float32).reshape(-1, 1, 2)))
            area_ratio = float(area / max(1, w * h))
        except Exception:
            area_ratio = 0.0

    # Thresholds are intentionally conservative. The scanner can still allow
    # a manual capture; these metrics are guidance, not a hard OCR rejection.
    sharp_score = max(0.0, min(1.0, math.log1p(sharpness) / math.log1p(900.0)))
    exposure_score = max(0.0, 1.0 - min(1.0, clipped_dark * 8.0 + clipped_light * 5.0))
    brightness_score = max(0.0, min(1.0, 1.0 - abs(mean - 150.0) / 150.0))
    contrast_score = max(0.0, min(1.0, std / 65.0))
    coverage_score = max(0.0, min(1.0, (area_ratio - 0.12) / 0.20)) if area_ratio else 0.5
    overall = (
        sharp_score * 0.35 +
        exposure_score * 0.20 +
        brightness_score * 0.15 +
        contrast_score * 0.10 +
        coverage_score * 0.20
    )

    return {
        "width": int(w),
        "height": int(h),
        "megapixels": round((w * h) / 1_000_000.0, 2),
        "sharpness": round(sharpness, 2),
        "sharpness_score": round(sharp_score, 4),
        "brightness": round(mean, 2),
        "contrast": round(std, 2),
        "clipped_dark_ratio": round(clipped_dark, 4),
        "clipped_light_ratio": round(clipped_light, 4),
        "glare_ratio": round(glare, 4),
        "page_area_ratio": round(area_ratio, 4),
        "overall_score": round(overall, 4),
    }


def _high_res_warp(image: np.ndarray, source_points, method: str, orientation: str) -> np.ndarray:
    """Warp the original-resolution photo directly to a 3x canonical page.

    Alignment is selected on the lightweight OMR detector, but the final warp
    is calculated from the original camera pixels. This avoids the common
    accuracy loss caused by rectifying at 612x936 and then upscaling.
    """
    scale = _env_int("SCANNER_MASTER_SCALE", 3, 2, 5)
    out_w = int(omr.PAGE_W * scale)
    out_h = int(omr.PAGE_H * scale)
    points = omr._order_points(source_points)

    if method == "document_contour":
        x0, y0, x1, y1 = 0.0, 0.0, omr.PAGE_W - 1.0, omr.PAGE_H - 1.0
        targets = {
            "0": np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]),
            "90_cw": np.float32([[x1, y0], [x1, y1], [x0, y1], [x0, y0]]),
            "90_ccw": np.float32([[x0, y1], [x0, y0], [x1, y0], [x1, y1]]),
            "180": np.float32([[x1, y1], [x0, y1], [x0, y0], [x1, y0]]),
        }
    else:
        tl, tr, bl, br = omr.MARK_CENTERS[0], omr.MARK_CENTERS[1], omr.MARK_CENTERS[2], omr.MARK_CENTERS[3]
        targets = {
            "0": np.float32([tl, tr, br, bl]),
            "90_cw": np.float32([tr, br, bl, tl]),
            "90_ccw": np.float32([bl, tl, tr, br]),
            "180": np.float32([br, bl, tl, tr]),
        }

    dst = targets.get(orientation, targets["0"]) * scale
    matrix = cv2.getPerspectiveTransform(points, dst)
    warped = cv2.warpPerspective(
        image, matrix, (out_w, out_h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped


def prepare_scan(image_bytes: bytes, question_count: int = 0) -> dict[str, Any]:
    """Prepare a camera/upload image for all ESSCAN AI modules."""
    image = decode_image(image_bytes)
    if image is None:
        raise ValueError("Unable to decode the uploaded image.")

    original_quality = _quality_metrics(image)

    # The existing alignment detector is deliberately reused so the scanner
    # and OMR make the same page decision. It is cheap enough for a final scan.
    try:
        warped_preview, registered, source_corners, alignment = omr._warp(
            image, question_count=question_count
        )
        method = alignment.get("alignment_method", "unknown")
        orientation = alignment.get("orientation", "0")
    except Exception:
        # If alignment fails, preserve the original for diagnostics. OCR can
        # still operate on it, but the response explicitly marks the page as
        # unnormalized so the UI can ask for a retake.
        return {
            "normalized": False,
            "original_quality": original_quality,
            "alignment": {"confidence": 0.0, "alignment_method": "failed"},
            "master_bytes": image_bytes,
            "omr_bytes": image_bytes,
        }

    # Use the original camera pixels for the final perspective transform.
    master = _high_res_warp(image, source_corners, method, orientation)

    # Gentle local contrast only. Do not binarize the master: handwriting
    # strokes and pen pressure are useful to both EasyOCR and Qwen.
    if _env_float("SCANNER_CLAHE_CLIP", 1.5, 0.0, 4.0) > 0:
        lab = cv2.cvtColor(master, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=_env_float("SCANNER_CLAHE_CLIP", 1.5, 0.5, 4.0),
            tileGridSize=(12, 12),
        )
        l = clahe.apply(l)
        master = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

    master_quality = _quality_metrics(master)
    quality = {
        **master_quality,
        "original": original_quality,
        "recommended": bool(
            original_quality["megapixels"] >= 1.5 and
            original_quality["sharpness_score"] >= 0.25 and
            original_quality["clipped_dark_ratio"] < 0.18
        ),
    }

    # OMR gets the canonical low-resolution page. It is deterministic and does
    # not benefit from the huge JPEG payload used for handwriting OCR.
    omr_image = cv2.resize(
        master, (int(omr.PAGE_W), int(omr.PAGE_H)), interpolation=cv2.INTER_AREA
    )
    master_bytes = _jpeg_bytes(master, _env_int("SCANNER_MASTER_JPEG_QUALITY", 94, 80, 98))
    omr_bytes = _jpeg_bytes(omr_image, 96)

    return {
        "normalized": True,
        "master_bytes": master_bytes,
        "omr_bytes": omr_bytes,
        "normalized_size": [int(master.shape[1]), int(master.shape[0])],
        "omr_size": [int(omr_image.shape[1]), int(omr_image.shape[0])],
        "source_corners": source_corners,
        "registered": bool(registered),
        "alignment": alignment,
        "quality": quality,
    }


def analyze_capture(image_bytes: bytes) -> dict[str, Any]:
    """Fast quality/alignment result for the live camera preview."""

    image = decode_image(image_bytes)

    if image is None:
        return {
            "ready": False,
            "error": "Unable to decode camera frame.",
        }

    # _quick_alignment() downsizes the submitted frame to at most 900 px on
    # its long edge. Return that exact coordinate-space size so the mobile
    # frontend can correctly map detected corners back onto the live video.
    image_h, image_w = image.shape[:2]
    detector_scale = min(1.0, 900.0 / max(image_w, image_h))
    source_frame_size = {
        "width": int(round(image_w * detector_scale)),
        "height": int(round(image_h * detector_scale)),
    }

    try:
        points, marker_count, geometry, confidence = omr._quick_alignment(image)
    except Exception as exc:
        return {
            "ready": False,
            "error": str(exc),
        }

    # ---------------------------------------------------------
    # Page was not detected.
    # _quick_alignment() returns:
    #   points = None
    #   marker_count = 0
    #   geometry = []
    #   confidence = 0.0
    # ---------------------------------------------------------
    if points is None:
        quality = _quality_metrics(image, None)

        return {
            "ready": False,
            "registered": False,
            "source_corners": None,
            "source_frame_size": source_frame_size,
            "alignment": {
                "alignment_method": "not_detected",
                "marker_count": int(marker_count),
                "confidence": round(float(confidence), 4),
                "automatic_detection": True,
            },
            "quality": quality,
            "recommendation": "Keep the entire answer sheet visible",
        }

    # ---------------------------------------------------------
    # Safety check: geometry should be a dictionary.
    # Prevents another .get() crash if the alignment function
    # returns an unexpected value.
    # ---------------------------------------------------------
    if not isinstance(geometry, dict):
        quality = _quality_metrics(image, points)

        return {
            "ready": False,
            "registered": marker_count >= 3,
            "source_corners": (
                np.asarray(points).tolist()
                if points is not None
                else None
            ),
            "source_frame_size": source_frame_size,
            "alignment": {
                "alignment_method": (
                    "registration_marks"
                    if marker_count >= 3
                    else "document_contour"
                ),
                "marker_count": int(marker_count),
                "confidence": round(float(confidence), 4),
                "automatic_detection": True,
            },
            "quality": quality,
            "error": "Invalid page geometry returned by OMR detector.",
            "recommendation": "Keep the entire answer sheet visible",
        }

    # ---------------------------------------------------------
    # Normal successful alignment
    # ---------------------------------------------------------
    quality = _quality_metrics(image, points)

    aspect = geometry.get("aspect_ratio", 0.0)

    ready = bool(
        points is not None
        and confidence >= 0.76
        and 0.52 <= aspect <= 0.75
        and geometry.get("skew_degrees", 90.0) <= 16.0
        and geometry.get("corner_error_degrees", 90.0) <= 24.0
        and quality["megapixels"] >= 0.7
        and quality["sharpness_score"] >= 0.18
        and quality["clipped_dark_ratio"] < 0.24
    )

    return {
        "ready": ready,
        "registered": marker_count >= 3,
        "source_corners": (
            np.asarray(points).tolist()
            if points is not None
            else None
        ),
        "source_frame_size": source_frame_size,
        "alignment": {
            "alignment_method": (
                "registration_marks"
                if marker_count >= 3
                else "document_contour"
            ),
            "marker_count": int(marker_count),
            "confidence": round(float(confidence), 4),
            **geometry,
            "automatic_detection": True,
        },
        "quality": quality,
        "recommendation": (
            "Ready to capture"
            if ready
            else "Move closer and keep the page flat"
            if aspect < 0.52
            else "Hold the phone steadier"
            if quality["sharpness_score"] < 0.18
            else "Improve lighting and avoid strong reflections"
            if quality["brightness"] < 70
            else "Keep the entire answer sheet visible"
        ),
    }