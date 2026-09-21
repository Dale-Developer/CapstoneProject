"""Compare Ollama vision models on one real answer-box crop.

Answers the only question that matters before paying to host anything:
does a bigger model actually read THIS handwriting well enough?

Usage, from backend/ with the venv active:

    # local
    python sweep_vision.py ocr_debug/crop_answer1.png

    # against the Ryzen box or a hosted server
    python sweep_vision.py ocr_debug/crop_answer1.png --host http://192.168.1.50:11434

    # specific models only
    python sweep_vision.py crop.png --models qwen2.5vl:3b,qwen2.5vl:7b

Pull the models on the SERVING machine first:
    ollama pull qwen2.5vl:7b
    ollama pull llama3.2-vision:11b
    ollama pull minicpm-v

Reports accuracy AND seconds per call. A model that reads perfectly but takes
four minutes per answer box is not usable for a class of forty, and you want
both numbers before deciding.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import io
import re
import sys
import time

import requests
from PIL import Image

# ---------------------------------------------------------------------------
# EDIT THIS: exactly what the student wrote on the crop you are testing.
# ---------------------------------------------------------------------------
GROUND_TRUTH = (
    "Artificial Intelligence is what helps us in securing "
    "our systems through automated threat detection "
    "and automated responses. This helps us mitigate such risks."
)

DEFAULT_MODELS = [
    "qwen2.5vl:3b",        # ~3.2GB  -- your current model
    "qwen2.5vl:7b",        # ~6GB    -- needs 16GB RAM
    "llama3.2-vision:11b", # ~7.9GB  -- needs 16GB, slower
    "minicpm-v",           # ~5.5GB  -- often strong on documents
]

PROMPT = (
    "You are a high-precision OCR system reading a scanned exam answer sheet.\n"
    "Transcribe the handwritten answer exactly as written.\n"
    "Do not correct spelling, grammar, punctuation, or wording.\n"
    "Do not add words that are not visible on the page.\n"
    "Do not explain or summarize. Return only the transcribed text."
)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", str(text or "").lower())).strip()


def char_score(candidate: str, truth: str) -> float:
    a, b = normalize(candidate), normalize(truth)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def word_recall(candidate: str, truth: str) -> tuple[int, int]:
    got, want = normalize(candidate).split(), normalize(truth).split()
    hits = sum(
        1 for w in want
        if any(difflib.SequenceMatcher(None, w, g).ratio() >= 0.7 for g in got)
    )
    return hits, len(want)


def encode(path: str, max_edge: int) -> str:
    image = Image.open(path).convert("RGB")
    if max(image.size) > max_edge:
        scale = max_edge / float(max(image.size))
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def run(host: str, model: str, image_b64: str, timeout: float) -> tuple[str, float, str]:
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [image_b64],
        "stream": False,
        "keep_alive": "15m",
        "options": {"temperature": 0.1, "num_predict": 512, "num_ctx": 8192},
    }
    started = time.monotonic()
    try:
        r = requests.post(f"{host}/api/generate", json=payload, timeout=timeout)
        elapsed = time.monotonic() - started
        if r.status_code >= 400:
            try:
                detail = str(r.json().get("error") or r.text)[:200]
            except Exception:
                detail = r.text[:200]
            return "", elapsed, f"HTTP {r.status_code}: {detail}"
        return str(r.json().get("response") or "").strip(), elapsed, ""
    except requests.exceptions.ReadTimeout:
        return "", time.monotonic() - started, f"timed out after {timeout:.0f}s"
    except Exception as exc:
        return "", time.monotonic() - started, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="An answer-box crop, e.g. ocr_debug/crop_answer1.png")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--max-edge", type=int, default=1400)
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()

    host = args.host.rstrip("/")
    try:
        tags = requests.get(f"{host}/api/tags", timeout=10).json()
        installed = {m["name"] for m in tags.get("models", [])}
    except Exception as exc:
        print(f"Cannot reach Ollama at {host}: {exc}")
        return 1

    print(f"host          : {host}")
    print(f"image         : {args.image}  (long edge capped at {args.max_edge})")
    print(f"ground truth  : {len(normalize(GROUND_TRUTH).split())} words")
    print(f"installed     : {', '.join(sorted(installed)) or '(none)'}")
    print()

    image_b64 = encode(args.image, args.max_edge)
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]

    print(f"{'model':<24} {'chars':>7} {'words':>9} {'sec':>7}")
    print("-" * 52)

    rows = []
    for model in wanted:
        if model not in installed and f"{model}:latest" not in installed:
            print(f"{model:<24} {'not pulled -- ollama pull ' + model}")
            continue
        text, elapsed, error = run(host, model, image_b64, args.timeout)
        if error:
            print(f"{model:<24} FAILED after {elapsed:.0f}s: {error}")
            continue
        c = char_score(text, GROUND_TRUTH)
        hits, total = word_recall(text, GROUND_TRUTH)
        rows.append((c, hits, model, text, elapsed))
        print(f"{model:<24} {c:>6.1%} {hits:>4}/{total:<4} {elapsed:>6.1f}")

    if not rows:
        print("\nNothing ran. Pull a model on the serving machine and retry.")
        return 1

    rows.sort(reverse=True, key=lambda r: (r[0], r[1]))
    print()
    print("=" * 52)
    for c, hits, model, text, elapsed in rows:
        print(f"\n--- {model}   {c:.1%} chars, {hits} words, {elapsed:.0f}s ---")
        print(text or "(empty)")

    best_c, _, best_model, _, best_sec = rows[0]
    print()
    print("=" * 52)
    print("--- DECIDING ---")
    print(f"Best: {best_model} at {best_c:.1%} character accuracy, {best_sec:.0f}s per answer box.")
    print()
    if best_c < 0.80:
        print("No model cleared 80%. Hosting a bigger one will NOT fix that -- hosting")
        print("solves memory, not accuracy. Before spending anything, retake the scan")
        print("in daylight with a darker pen and re-run: capture quality moves this")
        print("number more than model size does.")
    else:
        per_sheet = best_sec * 2
        print(f"That clears 80%. At roughly {per_sheet:.0f}s per sheet (2 answer boxes),")
        print(f"a class of 40 takes about {per_sheet * 40 / 60:.0f} minutes of pure")
        print("inference. Decide whether that is acceptable before committing, and")
        print("check whether a smaller max-edge keeps the accuracy at lower cost:")
        print(f"    python sweep_vision.py {args.image} --models {best_model} --max-edge 900")
    return 0


if __name__ == "__main__":
    sys.exit(main())
