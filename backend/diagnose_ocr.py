"""Run the ESSCAN essay OCR on one image and report every stage.

Usage, from the backend/ directory:

    python diagnose_ocr.py path/to/scan.jpg
    python diagnose_ocr.py path/to/scan.jpg --answers 2 --page-index 0 --no-mcq

Writes the rectified page and each answer-box crop to ./ocr_debug/ so you can
see what the recognizer was actually given. If the crop image looks wrong, the
problem is geometry or alignment. If the crop looks right and the text is still
empty, the problem is the recognizer.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

OUT = Path("ocr_debug")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--answers", type=int, default=1,
                        help="How many answer boxes are printed on this page (1 or 2).")
    parser.add_argument("--page-index", type=int, default=0,
                        help="Position of this page among the exam's essay pages.")
    parser.add_argument("--no-mcq", action="store_true",
                        help="Set when the exam has NO multiple-choice section.")
    args = parser.parse_args()

    src = Path(args.image)
    if not src.is_file():
        print(f"No such file: {src}")
        return 1

    # ---- 0. Load .env, then confirm which code is running -----------------
    # uvicorn loads backend/.env via python-dotenv before importing anything.
    # A standalone script does not, so without this every setting reported
    # below would be the CODE default and .env tuning would be invisible --
    # you would tune a file the diagnostic never reads.
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent / ".env"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            print(f".env           : loaded from {env_path}")
        else:
            print(f".env           : NOT FOUND at {env_path} (using code defaults)")
    except ImportError:
        print(".env           : python-dotenv not installed (using code defaults)")

    try:
        from services import sheet_layout as layout
    except ImportError:
        print("FAIL: services/sheet_layout.py not found.")
        print("      The patch is not installed, or you are not running from backend/.")
        return 1

    import services.ocr_hybrid as H

    patched = hasattr(H, "_clean_ollama_text") and hasattr(H, "_is_rule_artifact")
    print(f"sheet_layout   : loaded (CROP_INSET_TOP={layout.CROP_INSET_TOP})")
    print(f"ocr_hybrid     : {'PATCHED' if patched else 'OLD VERSION STILL LOADED'}")
    if not patched:
        print("      -> ocr_hybrid.py was not replaced, or __pycache__ is stale.")
        print("      -> find . -name __pycache__ -type d -exec rm -rf {} +")
        return 1
    print(f"decoder        : {os.getenv('OCR_DECODER', 'beamsearch')}"
          f"  width {os.getenv('OCR_BEAM_WIDTH', '10')}")
    print(f"resolution     : target {os.getenv('OCR_TARGET_WIDTH', '2200')}"
          f"  canvas {os.getenv('OCR_CANVAS_SIZE', '3200')}"
          f"  mag {os.getenv('OCR_MAG_RATIO', '1.25')}")
    print(f"variants       : {os.getenv('OCR_MULTIPASS_VARIANTS', 'original,clahe')}")

    # ---- Is the second engine actually alive? -----------------------------
    # An empty "ollama:" line in the extraction below is ambiguous: the model
    # may have been asked and returned nothing, or never asked at all. Probe
    # it explicitly so a silently-absent verifier cannot be mistaken for a
    # verifier that agreed.
    print()
    print("--- OLLAMA VERIFIER ---")
    verify_on = H._env_bool("OLLAMA_OCR_VERIFY", True)
    print(f"OLLAMA_OCR_VERIFY : {verify_on}")
    print(f"base url          : {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")
    print(f"model             : {os.getenv('OLLAMA_VISION_MODEL', 'qwen2.5vl:3b')}")
    if not verify_on:
        print("  ** Verification is DISABLED. EasyOCR is your only engine.")
    else:
        H.invalidate_service_cache()
        up = H.ollama_available()
        print(f"reachable         : {up}")
        if not up:
            print(f"  error           : {H.ollama_error()}")
            print("  ** The vision verifier is not running, so every low-confidence")
            print("     answer is EasyOCR's word alone. Start it with:  ollama serve")
            print(f"     and confirm the model is pulled: ollama pull "
                  f"{os.getenv('OLLAMA_VISION_MODEL', 'qwen2.5vl:3b')}")
    print(f"essay trigger     : below {os.getenv('OLLAMA_ESSAY_MIN_CONFIDENCE', '0.72')} confidence")
    print()

    OUT.mkdir(exist_ok=True)
    image_bytes = src.read_bytes()

    # ---- 1. Scanner: did the page rectify? --------------------------------
    from services.scanner import prepare_scan

    try:
        prepared = prepare_scan(image_bytes, question_count=0)
    except Exception as exc:
        print(f"prepare_scan raised {type(exc).__name__}: {exc}")
        prepared = {"normalized": False, "alignment": {}, "quality": {}}

    normalized = bool(prepared.get("normalized"))
    alignment = prepared.get("alignment", {}) or {}
    quality = prepared.get("quality", {}) or {}

    print("--- SCANNER ---")
    print(f"normalized     : {normalized}")
    print(f"method         : {alignment.get('alignment_method')}")
    print(f"marks found    : {alignment.get('marker_count')}")
    print(f"confidence     : {alignment.get('confidence')}")
    print(f"sharpness      : {quality.get('sharpness')} (score {quality.get('sharpness_score')})")
    print(f"brightness     : {quality.get('brightness')}  contrast {quality.get('contrast')}")
    print(f"dark clipping  : {quality.get('clipped_dark_ratio')}   glare {quality.get('glare_ratio')}")
    print(f"overall        : {quality.get('overall_score')}")
    if not normalized:
        print()
        print("  ** The page did not rectify. All four corner marks must be visible,")
        print("     the sheet flat, and the frame free of heavy shadow. Fixed crop")
        print("     coordinates mean nothing on an unrectified photo -- the patched")
        print("     code falls back to reading the whole page instead.")
    print()

    from PIL import Image

    work = prepared.get("master_bytes") or image_bytes
    page = Image.open(io.BytesIO(work)).convert("RGB")
    page.save(OUT / "00_page.png")
    print(f"wrote {OUT/'00_page.png'}  ({page.width}x{page.height})")

    # ---- 2. Geometry: where will it crop? ---------------------------------
    has_mcq = not args.no_mcq
    count = max(1, min(layout.MAX_ESSAYS_PER_PAGE, args.answers))
    top = layout.essay_content_top(has_mcq, args.page_index)
    mode = layout.essay_student_id_mode(has_mcq, args.page_index)

    print()
    print("--- GEOMETRY ---")
    print(f"has_mcq={has_mcq}  page_index={args.page_index}  -> header mode '{mode}', top={top}")
    print(f"answer boxes on this page: {count}")

    for i in range(count):
        x1, y1, x2, y2 = layout.essay_crop_box(top, count, i, page.width, page.height)
        _, by, _, bh = layout.essay_box(top, count, i)
        guides = layout.guide_lines(by, bh)
        first_px = (layout.PAGE_H - guides[0]) * (page.height / layout.PAGE_H)
        print(f"  box {i}: crop ({x1},{y1})-({x2},{y2})  "
              f"first guide line at y={first_px:.0f}px  "
              f"headroom={first_px - y1:.0f}px")
        if first_px <= y1:
            print("        ** CROP STARTS BELOW THE FIRST LINE -- the top line will be lost.")

    # ---- 3. Run the real extractor ---------------------------------------
    print()
    print("--- EXTRACTION ---")
    result = H.extract_essay_page(
        image_bytes,
        answer_count=count,
        has_mcq=has_mcq,
        prepared_scan=prepared,
        page_index=args.page_index,
    )

    if result.get("degraded"):
        print("degraded=True (page was not rectified; whole-page fallback was used)")

    for i, answer in enumerate(result.get("answers") or []):
        x1, y1, x2, y2 = layout.essay_crop_box(top, count, i, page.width, page.height)
        if x2 > x1 and y2 > y1:
            page.crop((x1, y1, x2, y2)).save(OUT / f"crop_answer{i + 1}.png")
            print(f"wrote {OUT}/crop_answer{i + 1}.png  <-- LOOK AT THIS")
        plaus = answer.get("plausibility")
        print(f"  answer {i + 1}: mode={answer.get('mode')} conf={answer.get('confidence')}"
              + (f" plausibility={plaus:.1%}" if plaus is not None else ""))
        if plaus is not None:
            gate = float(os.getenv("OCR_MIN_PLAUSIBILITY", "0.80"))
            verdict = "PASSES" if plaus >= gate else "FAILS -> verification triggered"
            print(f"    lexical gate: {plaus:.1%} vs {gate:.0%} threshold -- {verdict}")
            print(f"    (fraction of words that are real English; tracks accuracy far")
            print(f"     better than confidence, which cannot detect a confident wrong read)")
        print(f"    passes  : {answer.get('passes')}")
        print(f"    easyocr : {answer.get('easyocr')!r}")
        print(f"    ollama  : {answer.get('ollama')!r}")
        print(f"    FINAL   : {answer.get('answer')!r}")
        if not (answer.get("ollama") or "").strip():
            err = H.last_ollama_error()
            if err.get("error"):
                print(f"    ollama FAILED after {err['seconds']}s: {err['error']}")
        print()

    print("combined_text:")
    print(result.get("combined_text") or "(empty)")

    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=str))
    print()
    print(f"full result -> {OUT/'result.json'}")

    # ---- 4. Verdict -------------------------------------------------------
    print()
    print("--- WHAT TO CHECK ---")
    if any(not (a.get("ollama") or "").strip() for a in (result.get("answers") or [])):
        if H._env_bool("OLLAMA_OCR_VERIFY", True) and not H.ollama_available():
            print("Ollama returned nothing because it is NOT RUNNING -- see above.")
            print("Fix that before tuning anything else: a second opinion on a")
            print("0.61-confidence transcription is worth more than any threshold.")
            print()
    if not (result.get("combined_text") or "").strip():
        print("No text came back. Open crop_answer1.png:")
        print("  * crop is blank or shows the wrong part of the page -> geometry/alignment")
        print("  * crop shows the handwriting clearly              -> recognizer")
        print("    then try: OCR_TEXT_THRESHOLD=0.30 OCR_LOW_TEXT=0.15 python diagnose_ocr.py ...")
    else:
        print("Text came back. Compare it against crop_answer1.png word by word,")
        print("and check the FIRST line specifically -- that is the line the old")
        print("crop geometry used to lose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
