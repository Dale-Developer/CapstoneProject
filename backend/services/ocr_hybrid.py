"""
ESSCAN hybrid OCR engine.

Scope:
- Fine-tuned EasyOCR V5.2 remains the primary recognizer.
- OpenCV preprocessing provides multiple OCR views of the same image.
- Low-confidence/ambiguous regions are re-read with EasyOCR beam search.
- Local Ollama vision is a SECOND-OPINION verifier, not the primary OCR engine.
- The existing FastAPI endpoints and React UI contracts are preserved.

This module is intentionally limited to OCR extraction and does not change
grading, exam generation, authentication, or frontend behavior.
"""
from __future__ import annotations

import base64
import io
import math
import os
import re
import threading
from difflib import SequenceMatcher
from typing import Any

import cv2
import numpy as np
import requests
from PIL import Image

from services.ocr_match import (
    _get_reader,
    easyocr_available as _easyocr_available_raw,
    easyocr_error as _easyocr_error_raw,
    ollama_available as _ollama_available_raw,
    ollama_error as _ollama_error_raw,
)
from services.runtime import TTLValue, map_pages
from services.scanner import prepare_scan


# ---------------------------------------------------------------------------
# Cached availability probes
# ---------------------------------------------------------------------------
# ollama_available() performs a real HTTP round-trip and was previously called
# once per page plus twice more when building the response — five 2-second
# timeouts on a machine where Ollama is not running. Caching the answer for a
# few seconds keeps the check honest while removing it from the hot path.

_OLLAMA_TTL = float(os.getenv("OLLAMA_PROBE_TTL_SECONDS", "20"))
_ollama_up = TTLValue(_ollama_available_raw, _OLLAMA_TTL)
_ollama_err = TTLValue(_ollama_error_raw, _OLLAMA_TTL)
# EasyOCR readiness never changes after the reader is built, so it is cached
# for much longer.
_easyocr_up = TTLValue(_easyocr_available_raw, 300.0)
_easyocr_err = TTLValue(_easyocr_error_raw, 300.0)


def ollama_available() -> bool:
    return bool(_ollama_up.get())


def ollama_error():
    return _ollama_err.get()


def easyocr_available() -> bool:
    return bool(_easyocr_up.get())


def easyocr_error():
    return _easyocr_err.get()


def invalidate_service_cache() -> None:
    """Force the next availability check to hit the network again."""
    for cache in (_ollama_up, _ollama_err, _easyocr_up, _easyocr_err):
        cache.invalidate()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def _similarity(a: str, b: str) -> float:
    a = re.sub(r"[^a-z0-9]+", "", _normalize(a))
    b = re.sub(r"[^a-z0-9]+", "", _normalize(b))
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def _resize_for_ocr(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    target_width = _env_int("OCR_TARGET_WIDTH", 1800, 800, 5000)
    max_width = _env_int("OCR_MAX_WIDTH", 2400, target_width, 6000)
    max_upscale = _env_float("OCR_MAX_UPSCALE", 3.5, 1.0, 8.0)

    scale = 1.0
    if w < target_width:
        scale = min(max_upscale, target_width / max(1, w))
    elif w > max_width:
        scale = max_width / float(w)

    if abs(scale - 1.0) > 0.01:
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=interpolation)
    return image


class _LazyVariants:
    """Preprocessed OCR views of one page, computed only when asked for.

    The previous version eagerly built five full-page variants (CLAHE,
    sharpen, Otsu, adaptive threshold) on every call, then discarded the ones
    that were not requested — and in the common case where the first pass
    already succeeds, the fallback variants are never needed at all. On a
    1800px page that was several hundred milliseconds of pure waste per
    answer box. Variants are now computed on first access and memoised.
    """

    def __init__(self, image: np.ndarray, names: list[str]):
        self._base = _resize_for_ocr(image)
        self._gray = None
        self._cache: dict[str, np.ndarray] = {"original": self._base}
        self._names = names

    def keys(self) -> list[str]:
        return list(self._names)

    def __contains__(self, name: str) -> bool:
        return name in self._names

    def __len__(self) -> int:
        return len(self._names)

    @property
    def gray(self) -> np.ndarray:
        if self._gray is None:
            self._gray = cv2.cvtColor(self._base, cv2.COLOR_BGR2GRAY)
        return self._gray

    def _clahe(self) -> np.ndarray:
        return cv2.createCLAHE(
            clipLimit=_env_float("OCR_CLAHE_CLIP", 2.0, 0.5, 8.0),
            tileGridSize=(8, 8),
        ).apply(self.gray)

    def __getitem__(self, name: str) -> np.ndarray:
        if name in self._cache:
            return self._cache[name]

        if name == "clahe":
            value = self._clahe()
        elif name == "sharpen":
            clahe = self["clahe"]
            blur = cv2.GaussianBlur(clahe, (0, 0), sigmaX=1.0)
            value = cv2.addWeighted(clahe, 1.65, blur, -0.65, 0)
        elif name == "otsu":
            source = cv2.GaussianBlur(self.gray, (3, 3), 0)
            _, value = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif name == "adaptive":
            block = _env_int("OCR_ADAPTIVE_BLOCK_SIZE", 31, 11, 101)
            if block % 2 == 0:
                block += 1
            value = cv2.adaptiveThreshold(
                self["clahe"], 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, block, _env_int("OCR_ADAPTIVE_C", 11, 1, 30),
            )
        else:
            value = self._base

        self._cache[name] = value
        return value


def _preprocess_variants(image: np.ndarray) -> _LazyVariants:
    known = {"original", "clahe", "sharpen", "otsu", "adaptive"}
    requested = os.getenv("OCR_MULTIPASS_VARIANTS", "original,clahe")
    names = [x.strip().lower() for x in requested.split(",") if x.strip() in known]
    return _LazyVariants(image, names or ["original", "clahe", "adaptive"])


def _easyocr_kwargs(recheck: bool = False) -> dict[str, Any]:
    if recheck:
        return {
            "detail": 1,
            "paragraph": False,
            "decoder": "beamsearch",
            "beamWidth": _env_int("OCR_BEAM_WIDTH", 10, 1, 50),
            "min_size": _env_int("OCR_RECHECK_MIN_SIZE", 3, 1, 30),
            "contrast_ths": _env_float("OCR_CONTRAST_THS", 0.05, 0, 1),
            "adjust_contrast": _env_float("OCR_ADJUST_CONTRAST", 0.7, 0, 1),
            "text_threshold": _env_float("OCR_RECHECK_TEXT_THRESHOLD", 0.35, 0.05, 1),
            "low_text": _env_float("OCR_RECHECK_LOW_TEXT", 0.15, 0.01, 1),
            "link_threshold": _env_float("OCR_RECHECK_LINK_THRESHOLD", 0.20, 0.01, 1),
            "canvas_size": _env_int("OCR_RECHECK_CANVAS_SIZE", 2200, 600, 6000),
            "mag_ratio": _env_float("OCR_RECHECK_MAG_RATIO", 1.5, 1, 4),
            "add_margin": _env_float("OCR_ADD_MARGIN", 0.10, 0, 0.5),
        }
    return {
        "detail": 1,
        "paragraph": False,
        "decoder": os.getenv("OCR_DECODER", "greedy"),
        "beamWidth": _env_int("OCR_BEAM_WIDTH", 5, 1, 20),
        "min_size": _env_int("OCR_MIN_SIZE", 5, 1, 50),
        "contrast_ths": _env_float("OCR_CONTRAST_THS", 0.05, 0, 1),
        "adjust_contrast": _env_float("OCR_ADJUST_CONTRAST", 0.7, 0, 1),
        "text_threshold": _env_float("OCR_TEXT_THRESHOLD", 0.45, 0.05, 1),
        "low_text": _env_float("OCR_LOW_TEXT", 0.25, 0.01, 1),
        "link_threshold": _env_float("OCR_LINK_THRESHOLD", 0.25, 0.01, 1),
        "canvas_size": _env_int("OCR_CANVAS_SIZE", 2400, 800, 6000),
        "mag_ratio": _env_float("OCR_MAG_RATIO", 1.15, 1, 4),
        "add_margin": _env_float("OCR_ADD_MARGIN", 0.10, 0, 0.5),
    }


# A single EasyOCR Reader wraps torch modules that are not documented as
# thread-safe. Pages are processed in parallel to overlap the slow parts
# (OpenCV preprocessing and Ollama network calls), so recognition itself is
# serialized behind this lock. The parallelism still pays off because the
# lock is only held during recognition, not during the seconds spent waiting
# on Ollama.
_reader_lock = threading.RLock()


def _read_text(reader, image, **kwargs):
    with _reader_lock:
        return reader.readtext(image, **kwargs)


def _bbox_rect(bbox):
    xs = [float(p[0]) for p in bbox]
    ys = [float(p[1]) for p in bbox]
    return min(xs), min(ys), max(xs), max(ys)


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2]-a[0]) * max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _candidate(result, source):
    if not isinstance(result, (list, tuple)) or len(result) < 3:
        return None
    bbox, text, confidence = result[:3]
    text = str(text or "").strip()
    if not text:
        return None
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return {
        "bbox": [[float(x), float(y)] for x, y in bbox],
        "rect": _bbox_rect(bbox),
        "text": text,
        "confidence": max(0.0, min(1.0, confidence)),
        "source": source,
    }


def _cluster(candidates):
    clusters: list[list[dict[str, Any]]] = []
    for cand in sorted(candidates, key=lambda x: (-x["confidence"], x["rect"][1], x["rect"][0])):
        best = None
        best_score = 0.0
        for i, cluster in enumerate(clusters):
            rep = max(cluster, key=lambda x: x["confidence"])
            score = _iou(cand["rect"], rep["rect"])
            if score > best_score:
                best, best_score = i, score
        if best is not None and best_score >= 0.25:
            clusters[best].append(cand)
        else:
            clusters.append([cand])
    return clusters


def _reconstruct_lines(winners):
    if not winners:
        return []
    ordered = sorted(winners, key=lambda x: (((x["rect"][1] + x["rect"][3]) / 2), x["rect"][0]))
    heights = [max(1.0, x["rect"][3] - x["rect"][1]) for x in ordered]
    line_tol = max(8.0, float(np.median(heights)) * 0.65)
    lines = []
    for item in ordered:
        cy = (item["rect"][1] + item["rect"][3]) / 2
        placed = False
        for line in lines:
            if abs(cy - line["cy"]) <= line_tol:
                line["items"].append(item)
                line["cy"] = float(np.mean([
                    (v["rect"][1] + v["rect"][3]) / 2 for v in line["items"]
                ]))
                placed = True
                break
        if not placed:
            lines.append({"cy": cy, "items": [item]})
    lines.sort(key=lambda x: x["cy"])
    return [sorted(line["items"], key=lambda x: x["rect"][0]) for line in lines]


def _easyocr_passes(image: np.ndarray) -> tuple[str, float, list[dict[str, Any]], dict[str, int]]:
    """Efficient EasyOCR: one normal pass, one preprocessing fallback.

    Running EasyOCR's detector five times on the same page is expensive.
    V5.2 is therefore used once on the original image first. CLAHE/adaptive
    preprocessing is only used when the first result is weak.
    """
    reader = _get_reader()
    if reader is None:
        return "", 0.0, [], {}

    variants = _preprocess_variants(image)
    ordered_names = variants.keys()
    if not ordered_names:
        return "", 0.0, [], {}

    all_candidates: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    def run_variant(name: str):
        try:
            results = _read_text(reader, variants[name], **_easyocr_kwargs(False))
        except Exception:
            results = []
        candidates = [c for r in results or [] if (c := _candidate(r, name))]
        counts[name] = len(candidates)
        return candidates

    # Primary recognition pass.
    primary_name = "original" if "original" in variants else ordered_names[0]
    primary = run_variant(primary_name)
    all_candidates.extend(primary)

    def select_winners(candidates):
        if not candidates:
            return []
        clusters = _cluster(candidates)
        winners = []
        for cluster in clusters:
            by_text: dict[str, list[dict[str, Any]]] = {}
            for item in cluster:
                key = _normalize(item["text"])
                by_text.setdefault(key, []).append(item)
            best = None
            for items in by_text.values():
                avg = sum(i["confidence"] for i in items) / len(items)
                repeat_bonus = min(0.15, 0.04 * (len(items) - 1))
                score = avg + repeat_bonus
                candidate = max(items, key=lambda x: x["confidence"]).copy()
                candidate["selection_score"] = score
                if best is None or score > best["selection_score"]:
                    best = candidate
            if best:
                winners.append(best)
        return winners

    winners = select_winners(all_candidates)

    if winners:
        weights = [max(1, len(x["text"])) for x in winners]
        confidence = sum(x["confidence"] * w for x, w in zip(winners, weights)) / sum(weights)
    else:
        confidence = 0.0

    # Only spend another full detector pass when the first result is weak.
    fallback_threshold = _env_float("OCR_SECOND_PASS_CONFIDENCE", 0.62, 0, 1)
    min_text = _env_int("OCR_SECOND_PASS_MIN_TEXT", 3, 0, 1000)
    if (confidence < fallback_threshold or len(" ".join(x["text"] for x in winners)) < min_text):
        for name in ("clahe", "adaptive"):
            if name not in variants or name == primary_name:
                continue
            candidates = run_variant(name)
            if not candidates:
                continue
            all_candidates.extend(candidates)
            candidate_winners = select_winners(all_candidates)
            if candidate_winners:
                weights = [max(1, len(x["text"])) for x in candidate_winners]
                candidate_conf = sum(x["confidence"] * w for x, w in zip(candidate_winners, weights)) / sum(weights)
                if candidate_conf > confidence or not winners:
                    winners, confidence = candidate_winners, candidate_conf
            # Stop after the first useful fallback to keep CPU work bounded.
            if confidence >= fallback_threshold:
                break

    # Re-read only a small number of weak regions, using beam search.
    low_threshold = _env_float("OCR_RECHECK_CONFIDENCE", 0.55, 0, 1)
    limit = _env_int("OCR_REGION_RECHECK_LIMIT", 6, 0, 100)
    base = _resize_for_ocr(image)
    h, w = base.shape[:2]
    for item in sorted(winners, key=lambda x: x["confidence"])[:limit]:
        if item["confidence"] >= low_threshold:
            continue
        x1, y1, x2, y2 = item["rect"]
        pad = 0.12
        pw, ph = x2 - x1, y2 - y1
        xx1 = max(0, int(x1 - pw * pad))
        yy1 = max(0, int(y1 - ph * pad))
        xx2 = min(w, int(x2 + pw * pad))
        yy2 = min(h, int(y2 + ph * pad))
        crop = base[yy1:yy2, xx1:xx2]
        if crop.size == 0:
            continue
        try:
            reread = _read_text(reader, crop, **_easyocr_kwargs(True))
        except Exception:
            reread = []
        reread_candidates = [c for r in reread or [] if (c := _candidate(r, "recheck"))]
        if reread_candidates:
            candidate = max(reread_candidates, key=lambda x: x["confidence"])
            if candidate["confidence"] >= item["confidence"] + 0.03:
                item["text"] = candidate["text"]
                item["confidence"] = candidate["confidence"]
                item["source"] = "recheck"

    winners = [x for x in winners if x["confidence"] >= _env_float("OCR_MIN_REGION_CONFIDENCE", 0.12, 0, 1)]
    lines = _reconstruct_lines(winners)
    text = "\n".join(
        " ".join(item["text"] for item in line).strip()
        for line in lines
    ).strip()

    if winners:
        weights = [max(1, len(x["text"])) for x in winners]
        confidence = sum(x["confidence"] * w for x, w in zip(winners, weights)) / sum(weights)
    else:
        confidence = 0.0
    return text, confidence, winners, counts


def _image_base64(image: Image.Image) -> str:
    """Encode an image for Ollama as small as possible without losing strokes.

    The previous implementation sent lossless PNG at full scanner resolution.
    A normalized page is ~2000px wide, which produced 4-6 MB of base64 per
    request: the HTTP transfer and the model's image preprocessing together
    cost more than the actual generation. Capping the long edge and using
    high-quality JPEG cuts the payload by roughly 90% with no measurable
    difference in transcription quality for handwriting.
    """
    max_edge = _env_int("OLLAMA_IMAGE_MAX_EDGE", 1400, 512, 4096)
    if max(image.size) > max_edge:
        scale = max_edge / float(max(image.size))
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    if _env_bool("OLLAMA_IMAGE_JPEG", True):
        image.convert("RGB").save(
            buf, format="JPEG",
            quality=_env_int("OLLAMA_IMAGE_JPEG_QUALITY", 88, 60, 98),
            optimize=True,
        )
    else:
        image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def preload_ollama() -> str:
    """Ask Ollama to resident-load the vision model at server startup.

    Qwen2.5-VL 3B takes 5-15s to load from disk. Without this the first
    student whose handwriting needs verification pays that cost inside their
    upload request. An empty prompt with keep_alive loads the model and
    returns immediately.
    """
    if not _env_bool("OLLAMA_OCR_VERIFY", True) or not ollama_available():
        return "skipped"
    host = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
    try:
        response = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": _keep_alive(), "stream": False},
            timeout=_env_float("OLLAMA_PRELOAD_TIMEOUT_SECONDS", 120, 5, 600),
        )
        response.raise_for_status()
        return f"loaded ({model})"
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


def _keep_alive() -> str:
    """How long Ollama should hold the vision model in RAM between pages.

    Default 15 minutes. Without this Ollama unloads the model after 5 minutes
    of idle time and the next verification reloads 4.7 GB from disk.
    """
    return os.getenv("OLLAMA_KEEP_ALIVE", "15m")


def _ollama_vision(
    image: Image.Image,
    hint: str,
    purpose: str,
    roster_names: list[str] | None = None,
) -> tuple[str, float]:
    if not _env_bool("OLLAMA_OCR_VERIFY", True) or not ollama_available():
        return "", 0.0

    host = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
    timeout = _env_float("OLLAMA_OCR_TIMEOUT_SECONDS", 35, 5, 180)
    # Identification only ever needs a few short lines of output; essay
    # transcription genuinely needs more room. Capping generation length is
    # one of the most reliable ways to cut local-model latency, since it
    # directly bounds the number of decode steps — so identification gets
    # its own much lower ceiling instead of sharing the essay-answer default.
    num_predict = _env_int("OLLAMA_NUM_PREDICT", 512, 64, 4096)

    if purpose == "student_header":
        # Roster-constrained matching. Open-ended handwriting transcription
        # is a genuinely hard problem — the model has to invent spelling for
        # a name it has never seen. Asking it to instead PICK the closest
        # match from the real class roster turns that into a much easier
        # closed-set classification task: it only has to compare strokes
        # against a short list of known candidates, which local vision
        # models are markedly more accurate at, and it needs far fewer
        # output tokens (a name it copies vs. one it has to spell from
        # scratch), so this is also the single biggest lever on identification
        # latency. Falls back to open transcription when no roster is given.
        if roster_names:
            # Keep the prompt bounded for very large classes; ranked matching
            # downstream still works even if the true match is outside this
            # list (the model can say NONE and the fuzzy-text ranking is used).
            names_block = "\n".join(f"- {n}" for n in roster_names[:80])
            instruction = (
                "This student is enrolled in a class with this official roster:\n"
                f"{names_block}\n\n"
                "Look at the handwritten NAME field and identify which roster name "
                "it matches. Copy that name EXACTLY as it appears in the roster "
                "list above (same spelling). If the handwriting clearly does not "
                "match any name on the list, write NONE instead.\n"
                "Also read the handwritten STUDENT NO. and SECTION fields as written.\n"
                "Return only three lines: NAME: ..., NO: ..., SEC: ..."
            )
            num_predict = _env_int("OLLAMA_ID_NUM_PREDICT", 80, 32, 512)
        else:
            instruction = (
                "Read the handwritten NAME, STUDENT NO., and SECTION fields. "
                "Use the OCR hint only as a clue and correct it if the image disagrees. "
                "Return only three lines: NAME: ..., NO: ..., SEC: ..."
            )
            num_predict = _env_int("OLLAMA_ID_NUM_PREDICT", 80, 32, 512)
    else:
        instruction = (
            "Transcribe the handwritten answer exactly as written. "
            "Do not correct spelling, grammar, punctuation, or wording. "
            "Do not summarize. If unreadable, make the best effort and return the visible text."
        )

    prompt = (
        "You are a high-precision vision OCR verifier for a school answer sheet. Read only visible characters; never invent missing characters.\n"
        f"{instruction}\n"
        f"EasyOCR rough reading: {hint or '(none)'}"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [_image_base64(image)],
        "stream": False,
        "keep_alive": _keep_alive(),
        "options": {
            "temperature": 0.1,
            "num_predict": num_predict,
            "num_ctx": _env_int("OLLAMA_NUM_CTX", 4096, 1024, 16384),
        },
    }
    try:
        response = requests.post(f"{host}/api/generate", json=payload, timeout=timeout)
        response.raise_for_status()
        text = str(response.json().get("response") or "").strip()
        # Ollama does not provide a trustworthy calibrated OCR probability.
        # Treat it as a verifier and only use its confidence after agreement.
        return text, 0.5 if text else 0.0
    except Exception:
        return "", 0.0


def _crop_top(image: Image.Image) -> Image.Image:
    w, h = image.size
    return image.crop((0, 0, w, int(h * 0.27)))


def extract_text(
    image_bytes: bytes,
    prepared_scan: dict | None = None,
    roster: list[dict] | None = None,
) -> dict:
    """Page-1/header extraction for student identification.

    EasyOCR V5.2 is primary. Ollama vision is an independent second reader.
    When ``roster`` is supplied, Ollama is asked to pick the closest-matching
    name directly from the class roster instead of transcribing blind —
    this is both faster (far fewer output tokens for a name it copies vs.
    spells from scratch) and more accurate (closed-set matching against real
    candidates beats open-ended handwriting transcription). The existing
    match_students() logic remains responsible for the actual roster ranking
    shown to the professor; this only improves the text it ranks against.
    """
    try:
        prepared = prepared_scan if prepared_scan is not None else prepare_scan(image_bytes, question_count=0)
        work_bytes = prepared.get("master_bytes") or image_bytes
        pil = Image.open(io.BytesIO(work_bytes)).convert("RGB")
        arr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception:
        try:
            pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            arr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            prepared = {"normalized": False, "alignment": {"confidence": 0.0}}
        except Exception:
            return {"easyocr_text": "", "ollama_text": "", "combined_text": "", "easyocr_regions": []}

    header = _crop_top(pil)
    header_arr = cv2.cvtColor(np.array(header), cv2.COLOR_RGB2BGR)
    easy_text, confidence, regions, counts = _easyocr_passes(header_arr)

    if len(easy_text.strip()) < 3:
        easy_text, confidence, regions, counts = _easyocr_passes(arr)

    ollama_text = ""
    verify_threshold = _env_float("OLLAMA_OCR_MIN_CONFIDENCE", 0.62, 0, 1)
    # Do not wake a 4.7 GB local vision model for every student. EasyOCR is
    # trusted when it is clear; Ollama is only invoked for uncertain headers.
    if _env_bool("OLLAMA_OCR_VERIFY", True) and (
        not easy_text.strip() or confidence < verify_threshold
    ):
        roster_names = [str(s.get("name") or "").strip() for s in (roster or [])]
        roster_names = [n for n in roster_names if n]
        ollama_text, _ = _ollama_vision(header, easy_text, "student_header", roster_names=roster_names)
    combined = "\n".join(x for x in (easy_text, ollama_text) if x).strip()

    return {
        "easyocr_text": easy_text,
        "ollama_text": ollama_text,
        "combined_text": combined,
        "easyocr_regions": regions,
        "easyocr_confidence": round(confidence, 4),
        "multipass": True,
        "passes": counts,
        "scanner": {
            "normalized": bool(prepared.get("normalized")),
            "alignment": prepared.get("alignment", {}),
            "quality": prepared.get("quality", {}),
            "normalized_size": prepared.get("normalized_size"),
        },
    }


def extract_essay_page(
    image_bytes: bytes,
    answer_count: int = 2,
    has_mcq: bool = True,
    prepared_scan: dict | None = None,
) -> dict:
    """Extract handwritten essay answers from the current ESSCAN page layout.

    ``has_mcq`` determines whether this is a mixed-exam essay page (compact
    student-ID line) or the first page of an essay-only exam (full ID box).
    The current React upload UI is unchanged.
    """
    try:
        prepared = prepared_scan if prepared_scan is not None else prepare_scan(image_bytes, question_count=0)
        work_bytes = prepared.get("master_bytes") or image_bytes
        page = Image.open(io.BytesIO(work_bytes)).convert("RGB")
    except Exception:
        try:
            page = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            prepared = {"normalized": False, "alignment": {"confidence": 0.0}}
        except Exception:
            return {"answers": [], "easyocr_text": "", "ollama_text": "", "combined_text": ""}

    W, H = 612.0, 936.0
    # Values come directly from the current exam_pdf.py:
    # mixed essay pages use student_id_mode="line" -> top=806
    # essay-only first page uses student_id_mode="box" -> top=750
    top = 806.0 if has_mcq else 750.0
    bottom = 42.0
    gap = 14.0
    count = max(1, min(2, int(answer_count or 1)))
    box_h = max(95.0, min(340.0, (top - bottom - gap * max(0, count - 1)) / count))

    # Each answer box on the page is independent, so they are cropped up front
    # and recognized in parallel. The Ollama verification step is network I/O
    # bound, which is exactly where overlapping the work pays off.
    crops = []
    for index in range(count):
        y = top - (index + 1) * box_h - index * gap
        left, right = 76.0, 536.0
        crop_top = y + box_h - 46.0
        crop_bottom = y + 12.0

        sx = page.width / W
        sy = page.height / H
        x1 = max(0, int(left * sx))
        x2 = min(page.width, int(right * sx))
        y1 = max(0, int((H - crop_top) * sy))
        y2 = min(page.height, int((H - crop_bottom) * sy))

        if x2 <= x1 or y2 <= y1:
            continue
        crops.append((index, page.crop((x1, y1, x2, y2))))

    def read_answer(item):
        index, crop = item
        crop_arr = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2BGR)
        text, confidence, _, counts = _easyocr_passes(crop_arr)

        ollama_text = ""
        verify_threshold = _env_float("OLLAMA_OCR_MIN_CONFIDENCE", 0.62, 0, 1)
        if text.strip() == "" or confidence < verify_threshold:
            ollama_text, _ = _ollama_vision(crop, text, "essay")

        if text and ollama_text:
            agreement = _similarity(text, ollama_text)
            if agreement >= _env_float("OLLAMA_AGREEMENT_THRESHOLD", 0.70, 0, 1):
                final = text
                mode = "easyocr+ollama-agreement"
            else:
                final = text if confidence >= 0.55 else ollama_text
                mode = "easyocr-preferred" if confidence >= 0.55 else "ollama-fallback"
        elif ollama_text:
            final = ollama_text
            mode = "ollama-fallback"
        else:
            final = text
            mode = "easyocr"

        return {
            "index": index,
            "answer": final.strip(),
            "easyocr": text.strip(),
            "ollama": ollama_text.strip(),
            "confidence": round(confidence, 4),
            "mode": mode,
            "passes": counts,
        }

    results = map_pages(read_answer, crops) if len(crops) > 1 else [read_answer(c) for c in crops]

    answers = []
    easy_parts = []
    ollama_parts = []
    diagnostics = []
    for position, result in enumerate(results):
        if isinstance(result, Exception):
            # One unreadable box must not fail the whole page; record it as
            # empty so the professor sees a blank answer rather than an error.
            result = {
                "index": position, "answer": "", "easyocr": "", "ollama": "",
                "confidence": 0.0, "mode": f"error:{type(result).__name__}", "passes": {},
            }
        index = result.pop("index", position)
        answers.append(result)
        easy_parts.append(result["easyocr"])
        ollama_parts.append(result["ollama"])
        diagnostics.append({
            "answer": index + 1,
            "easyocrConfidence": result["confidence"],
            "mode": result["mode"],
        })

    final_parts = [a["answer"] for a in answers if a["answer"]]
    return {
        "answers": answers,
        "easyocr_text": "\n\n".join(easy_parts),
        "ollama_text": "\n\n".join(ollama_parts),
        "combined_text": "\n\n".join(final_parts),
        "diagnostics": diagnostics,
        "multipass": True,
        "ollamaVerification": bool(ollama_parts),
        "scanner": {
            "normalized": bool(prepared.get("normalized")),
            "alignment": prepared.get("alignment", {}),
            "quality": prepared.get("quality", {}),
            "normalized_size": prepared.get("normalized_size"),
        },
    }


__all__ = [
    "extract_text",
    "extract_essay_page",
    "easyocr_available",
    "easyocr_error",
    "ollama_available",
    "ollama_error",
]
