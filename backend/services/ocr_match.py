"""
ESSCAN OCR service.

Primary recognizer:
    User's verified EasyOCR V5.2 custom model
    None -> VGG -> BiLSTM -> CTC

Secondary pass:
    Local Ollama vision model for Page-1 student identification.

The V5.2 checkpoint is loaded through EasyOCR's official custom-model
mechanism using three matching files:
    handwriting_finetune_v5_2.pth
    handwriting_finetune_v5_2.yaml
    handwriting_finetune_v5_2.py
"""
import base64
import io
import os
import re
from difflib import SequenceMatcher
from typing import Any

from PIL import Image

try:
    import numpy as np
    import easyocr
    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


EASYOCR_MODEL_DIR = os.environ.get(
    "EASYOCR_MODEL_DIR",
    "./ai_models/easyocr_v5_2/model",
)
EASYOCR_USER_NETWORK_DIR = os.environ.get(
    "EASYOCR_USER_NETWORK_DIR",
    "./ai_models/easyocr_v5_2/user_network",
)
EASYOCR_RECOG_NETWORK = os.environ.get(
    "EASYOCR_RECOG_NETWORK",
    "handwriting_finetune_v5_2",
)
EASYOCR_GPU = os.environ.get("EASYOCR_GPU", "0") == "1"
EASYOCR_DOWNLOAD_ENABLED = os.environ.get(
    "EASYOCR_DOWNLOAD_ENABLED", "1"
) == "1"

OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL",
    "http://localhost:11434",
)
OLLAMA_VISION_MODEL = os.environ.get(
    "OLLAMA_VISION_MODEL",
    "qwen2.5vl:3b",
)
def _ollama_timeout() -> float:
    """Seconds to wait for an Ollama reply.

    Read per call, and named consistently with ocr_hybrid. This module used to
    define OLLAMA_TIMEOUT_SECONDS at import time while ocr_hybrid read
    OLLAMA_OCR_TIMEOUT_SECONDS, so raising the timeout in .env fixed essay
    transcription and left student identification on the old 25s default, on a
    variable that appears nowhere in .env. Identification then timed out while
    essays succeeded, which is a confusing failure to read.

    OLLAMA_TIMEOUT_SECONDS is still honoured if set, so an existing override
    keeps working.
    """
    for name in ("OLLAMA_TIMEOUT_SECONDS", "OLLAMA_OCR_TIMEOUT_SECONDS"):
        raw = os.environ.get(name)
        if raw:
            try:
                return max(5.0, min(600.0, float(raw)))
            except ValueError:
                continue
    return 25.0

_reader = None
_reader_error = None


def _resolve_backend_path(path: str) -> str:
    """Resolve relative model paths from the backend directory."""
    if os.path.isabs(path):
        return path
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(os.path.join(backend_dir, path))


def _validate_custom_model_files() -> None:
    model_dir = _resolve_backend_path(EASYOCR_MODEL_DIR)
    user_dir = _resolve_backend_path(EASYOCR_USER_NETWORK_DIR)

    model_path = os.path.join(
        model_dir,
        f"{EASYOCR_RECOG_NETWORK}.pth",
    )
    yaml_path = os.path.join(
        user_dir,
        f"{EASYOCR_RECOG_NETWORK}.yaml",
    )
    py_path = os.path.join(
        user_dir,
        f"{EASYOCR_RECOG_NETWORK}.py",
    )

    missing = [
        path for path in (model_path, yaml_path, py_path)
        if not os.path.isfile(path)
    ]

    if missing:
        raise FileNotFoundError(
            "Fine-tuned EasyOCR V5.2 files are missing:\n"
            + "\n".join(f" - {p}" for p in missing)
            + "\nCopy your V5.2 best_accuracy.pth to the model directory."
        )


def _get_reader():
    global _reader, _reader_error

    if _reader is not None:
        return _reader

    if not _EASYOCR_AVAILABLE:
        _reader_error = "easyocr/numpy is not installed."
        return None

    try:
        _validate_custom_model_files()

        model_dir = _resolve_backend_path(EASYOCR_MODEL_DIR)
        user_dir = _resolve_backend_path(EASYOCR_USER_NETWORK_DIR)

        os.makedirs(model_dir, exist_ok=True)
        os.makedirs(user_dir, exist_ok=True)

        _reader = easyocr.Reader(
            ["en"],
            gpu=EASYOCR_GPU,
            model_storage_directory=model_dir,
            user_network_directory=user_dir,
            recog_network=EASYOCR_RECOG_NETWORK,
            download_enabled=EASYOCR_DOWNLOAD_ENABLED,
            detector=True,
            recognizer=True,
            verbose=True,
        )
        _reader_error = None
    except Exception as exc:
        _reader = None
        _reader_error = f"{type(exc).__name__}: {exc}"

    return _reader


def easyocr_available() -> bool:
    return _get_reader() is not None


def easyocr_error() -> str | None:
    _get_reader()
    return _reader_error


def ollama_available() -> bool:
    if not _REQUESTS_AVAILABLE:
        return False
    try:
        resp = requests.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=2,
        )
        return resp.status_code == 200
    except Exception:
        return False


def ollama_error() -> str | None:
    if not _REQUESTS_AVAILABLE:
        return "The Python requests package is not installed."
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        if resp.status_code != 200:
            return f"Ollama returned HTTP {resp.status_code}."
        models = resp.json().get("models", [])
        names = [m.get("name", "") for m in models]
        if OLLAMA_VISION_MODEL not in names and not any(n.startswith(OLLAMA_VISION_MODEL + ":") for n in names):
            return f"Ollama is running, but the vision model '{OLLAMA_VISION_MODEL}' is not installed."
        return None
    except Exception as exc:
        return f"Cannot reach Ollama at {OLLAMA_BASE_URL}: {type(exc).__name__}: {exc}"


def _top_strip(image: Image.Image) -> Image.Image:
    w, h = image.size
    return image.crop((0, 0, w, int(h * 0.25)))


def _easyocr_extract(
    image: Image.Image,
    return_regions: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    reader = _get_reader()

    if not reader:
        return "", []

    try:
        arr = np.array(image.convert("RGB"))

        results = reader.readtext(
            arr,
            detail=1,
            paragraph=False,
        )

        regions = []
        texts = []

        for item in results:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue

            box, text, confidence = item[:3]

            text = str(text or "").strip()
            if not text:
                continue

            texts.append(text)
            regions.append({
                "box": box,
                "text": text,
                "confidence": round(float(confidence), 6),
            })

        return " ".join(texts).strip(), regions

    except Exception:
        return "", []


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ollama_extract(
    image: Image.Image,
    easyocr_hint: str,
) -> str:
    if not _REQUESTS_AVAILABLE:
        return ""

    prompt = (
        "This is a cropped photo of the top of a student's exam answer sheet. "
        "It has handwritten fields for Name, Student Number, and Section. "
        f"An OCR pass produced this rough, possibly incorrect reading: "
        f"\"{easyocr_hint.strip() or '(no text detected)'}\". "
        "Look at the actual handwriting and give your own independent reading. "
        "Correct the OCR guess when the image disagrees. "
        "Reply in exactly this format and nothing else:\n"
        "NAME: <name>\n"
        "NO: <student number>\n"
        "SEC: <section>"
    )

    payload = {
        "model": OLLAMA_VISION_MODEL,
        "prompt": prompt,
        "images": [_image_to_base64(image)],
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=_ollama_timeout(),
        )
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()
    except Exception:
        return ""


def extract_page(image_bytes: bytes, include_ollama: bool = False) -> dict:
    """
    Run V5.2 EasyOCR on a complete page.

    include_ollama is intentionally False for essay pages because Ollama is
    currently used as the independent Page-1 student-identification pass.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return {
            "easyocr_text": "",
            "easyocr_regions": [],
            "ollama_text": "",
        }

    text, regions = _easyocr_extract(image)

    ollama_text = ""
    if include_ollama:
        strip = _top_strip(image)
        header_text, header_regions = _easyocr_extract(strip)

        if header_text:
            # Preserve the full-page regions plus header regions as separate
            # diagnostic information.
            regions = regions + [
                {
                    "scope": "header",
                    "box": r["box"],
                    "text": r["text"],
                    "confidence": r["confidence"],
                }
                for r in header_regions
            ]

        ollama_text = (
            _ollama_extract(strip, header_text)
            if ollama_available()
            else ""
        )

    return {
        "easyocr_text": text,
        "easyocr_regions": regions,
        "ollama_text": ollama_text,
    }


def extract_text(image_bytes: bytes) -> dict:
    """
    Page-1 student identification extraction.

    The EasyOCR pass is deliberately restricted to the header crop so printed
    questionnaire/OMR content does not pollute roster matching. The raw
    EasyOCR boxes/confidences from that crop are retained.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return {
            "easyocr_text": "",
            "ollama_text": "",
            "combined_text": "",
            "easyocr_regions": [],
        }

    strip = _top_strip(image)
    easyocr_text, regions = _easyocr_extract(strip)

    if len(easyocr_text) < 3:
        # Fallback for unusually tall/cropped headers.
        easyocr_text, regions = _easyocr_extract(image)

    ollama_text = (
        _ollama_extract(strip, easyocr_text)
        if ollama_available()
        else ""
    )

    return {
        "easyocr_text": easyocr_text,
        "ollama_text": ollama_text,
        "combined_text": "\n".join(
            t for t in (
                easyocr_text,
                ollama_text,
            ) if t
        ),
        "easyocr_regions": regions,
    }


def _normalize(text: str) -> str:
    return re.sub(
        r"[^a-z0-9 ]",
        " ",
        (text or "").lower(),
    )


def _name_evidence(name: str, text: str) -> float:
    norm_text = _normalize(text)

    if not norm_text:
        return 0.0

    norm_name = _normalize(name)

    ratio = SequenceMatcher(
        None,
        norm_name,
        norm_text,
    ).ratio()

    tokens = [
        t for t in norm_name.split()
        if len(t) > 1
    ]

    hits = sum(
        1 for t in tokens
        if t in norm_text
    ) if tokens else 0

    token_ratio = (
        hits / len(tokens)
        if tokens else 0.0
    )

    return max(
        ratio,
        token_ratio * 0.9,
    )


def match_students(
    extraction: dict,
    roster: list[dict],
) -> list[dict]:
    easyocr_text = extraction.get(
        "easyocr_text",
        "",
    )

    ollama_text = extraction.get(
        "ollama_text",
        "",
    )

    results = []

    for student in roster:
        score_easyocr = _name_evidence(
            student["name"],
            easyocr_text,
        )

        score_ollama = _name_evidence(
            student["name"],
            ollama_text,
        )

        name_evidence = max(
            score_easyocr,
            score_ollama,
        )

        agreement_bonus = (
            0.15
            if (
                score_easyocr >= 0.5
                and score_ollama >= 0.5
            )
            else 0.0
        )

        # Student number was dropped as an identification signal: nothing
        # backed it (no student_number column on User; the printed field
        # used to be matched against the internal DB user_id, which
        # students never actually see). Name evidence now carries the
        # full weight that name + id used to share.
        confidence = min(
            1.0,
            (
                0.85 * name_evidence
                + agreement_bonus
            ),
        )

        results.append({
            **student,
            "confidence": round(
                confidence,
                3,
            ),
        })

    results.sort(
        key=lambda r: r["confidence"],
        reverse=True,
    )

    return results
