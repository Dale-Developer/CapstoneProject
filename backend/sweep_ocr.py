"""Sweep OCR settings against a known-correct transcription.

Usage, from backend/ with the venv active:

    python sweep_ocr.py "uploads\\student_submissions\\3\\3\\Sanchez_Fiona_3_answer_sheet_essay_page_1.jpg"

Edit GROUND_TRUTH below to match whatever the student actually wrote. Each
configuration is scored by character similarity against it, so the ranking is
measured rather than eyeballed.

Each run reloads the OCR module so the environment change takes effect, and
the EasyOCR reader is built once and reused, so the sweep costs roughly one
model load plus one pass per configuration.
"""
from __future__ import annotations

import difflib
import importlib
import os
import re
import sys
import time
import warnings

# ---------------------------------------------------------------------------
# EDIT THIS: exactly what the student wrote, line breaks and all.
# ---------------------------------------------------------------------------
GROUND_TRUTH = """Artificial Intelligence is what helps us in securing
our systems through automated threat detection
and automated responses. This helps us mitigate
such risks."""

# ---------------------------------------------------------------------------
# Configurations to try. Each is (name, {env var: value}).
# The first entry is the current default, as a baseline.
# ---------------------------------------------------------------------------
CONFIGS: list[tuple[str, dict[str, str]]] = [
    ("baseline (current defaults)", {}),

    # The beamsearch overflow warnings suggest its probabilities are saturating
    # on long lines. Greedy has no such failure mode.
    ("greedy decoder", {"OCR_DECODER": "greedy"}),

    # CRAFT links neighbouring characters into one box using the affinity map.
    # A higher threshold links less, so words stay separate and each is
    # recognised at its own scale instead of a whole line being squeezed into
    # the model's 600px input width.
    ("split words (link 0.40)", {"OCR_LINK_THRESHOLD": "0.40"}),
    ("split words (link 0.55)", {"OCR_LINK_THRESHOLD": "0.55"}),

    # The crop is mostly blank ruled paper, and canvas_size claws back the
    # upscale. Give the recognizer more pixels.
    ("bigger canvas", {"OCR_CANVAS_SIZE": "4200", "OCR_MAG_RATIO": "1.6"}),

    # Low contrast (25.7) is this scan's weakest measurement, and the CLAHE
    # pass already found more regions than the original.
    ("all preprocessing variants",
     {"OCR_MULTIPASS_VARIANTS": "original,clahe,sharpen,adaptive",
      "OCR_SECOND_PASS_CONFIDENCE": "0.95"}),

    # Detect fainter strokes.
    ("lower detection thresholds",
     {"OCR_TEXT_THRESHOLD": "0.30", "OCR_LOW_TEXT": "0.15"}),

    # The combination most likely to win, based on the three suspects above.
    ("combined",
     {"OCR_DECODER": "greedy", "OCR_LINK_THRESHOLD": "0.45",
      "OCR_CANVAS_SIZE": "4200", "OCR_MAG_RATIO": "1.6",
      "OCR_MULTIPASS_VARIANTS": "original,clahe,sharpen",
      "OCR_SECOND_PASS_CONFIDENCE": "0.95"}),
]

TUNABLE = [k for _, cfg in CONFIGS for k in cfg]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", str(text or "")).lower()).strip()


def score(candidate: str, truth: str) -> float:
    a, b = normalize(candidate), normalize(truth)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def word_recall(candidate: str, truth: str) -> tuple[int, int]:
    """How many ground-truth words appear, allowing close misspellings."""
    got = normalize(candidate).split()
    want = normalize(truth).split()
    hits = 0
    for word in want:
        if any(difflib.SequenceMatcher(None, word, g).ratio() >= 0.7 for g in got):
            hits += 1
    return hits, len(want)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"No such file: {path}")
        return 1

    warnings.filterwarnings("ignore")

    # Load backend/.env first so the baseline row reflects your real
    # configuration rather than the code defaults. Each config below then
    # overrides specific keys on top of it.
    try:
        from dotenv import load_dotenv
        from pathlib import Path as _P
        env_path = _P(__file__).resolve().parent / ".env"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass

    from services.scanner import prepare_scan

    image_bytes = open(path, "rb").read()
    try:
        prepared = prepare_scan(image_bytes, question_count=0)
    except Exception as exc:
        print(f"prepare_scan failed: {exc}")
        prepared = None

    print(f"ground truth: {len(normalize(GROUND_TRUTH).split())} words\n")
    print(f"{'configuration':<32} {'chars':>7} {'words':>9} {'sec':>6}")
    print("-" * 58)

    results = []
    for name, env in CONFIGS:
        # Clear every tunable first so configs never leak into each other.
        for key in TUNABLE:
            os.environ.pop(key, None)
        os.environ.update(env)

        # Reload so module-level defaults re-read the environment. The
        # EasyOCR reader itself lives in ocr_match and is not rebuilt.
        import services.ocr_hybrid as H
        importlib.reload(H)

        start = time.monotonic()
        try:
            result = H.extract_essay_page(
                image_bytes, answer_count=1, has_mcq=True,
                prepared_scan=prepared, page_index=0,
            )
            text = result.get("combined_text") or ""
        except Exception as exc:
            print(f"{name:<32} FAILED: {type(exc).__name__}: {exc}")
            continue
        elapsed = time.monotonic() - start

        char = score(text, GROUND_TRUTH)
        hits, total = word_recall(text, GROUND_TRUTH)
        results.append((char, hits, name, text, elapsed))
        print(f"{name:<32} {char:>6.1%} {hits:>4}/{total:<4} {elapsed:>6.1f}")

    print()
    results.sort(reverse=True, key=lambda r: (r[0], r[1]))
    print("=" * 58)
    print("BEST:", results[0][2] if results else "(none)")
    print("=" * 58)
    for char, hits, name, text, _ in results[:3]:
        print(f"\n--- {name}  ({char:.1%} chars, {hits} words) ---")
        print(text or "(empty)")

    print("\n\nApply the winner by putting its variables in backend\\.env,")
    print("then restart uvicorn. The settings are listed in CONFIGS above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
