"""Grade one answer twice -- as written, and as the OCR read it.

Separates two questions that look identical from the outside:

    "is my grading engine wrong?"
    "is my grading engine correct but reading garbage?"

Usage, from backend/ with the venv active:

    python diagnose_grading.py --question-id 5

Edit TRUE_TEXT and OCR_TEXT below, or pass --true-text / --ocr-text.

If the true-text score is high and the OCR-text score is low, the grader is
fine and every point of difference is transcription loss. That number -- the
grading cost of OCR error -- is worth reporting on its own.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# What the student actually wrote.
TRUE_TEXT = (
    "Artificial Intelligence is what helps us in securing "
    "our systems through automated threat detection "
    "and automated responses. This helps us mitigate such risks."
)

# What the OCR pipeline produced from the same handwriting.
OCR_TEXT = (
    ". .\n"
    "BEEEgre Brfifice Dffoue s wtep it pepres we sccning\n"
    "ar and ar a a beles Bhratdetection iitgats\n"
    "sce sists."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-id", type=int, required=True,
                    help="An essay question_id from the exam_questions table.")
    ap.add_argument("--true-text", default=TRUE_TEXT)
    ap.add_argument("--ocr-text", default=OCR_TEXT)
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        env = Path(__file__).resolve().parent / ".env"
        if env.is_file():
            load_dotenv(env, override=False)
    except ImportError:
        pass

    from database import SessionLocal
    from models.exam_question import ExamQuestion
    from services import essay_grader, nlp_spacy
    from services.rubric import load_rubric_for_question

    db = SessionLocal()
    try:
        q = db.query(ExamQuestion).filter(
            ExamQuestion.question_id == args.question_id
        ).first()
        if q is None:
            print(f"No question with id {args.question_id}.")
            return 1

        print(f"question   : {str(q.question_text or '')[:90]}")
        print(f"points     : {q.points}")
        print(f"format     : {q.expected_response_format}")
        print(f"answer key : {str(q.answer_key or '(none)')[:90]}")

        info = nlp_spacy.sbert_info()
        print(f"sbert      : loaded={info['loaded']}"
              + ("" if info["loaded"] else f"  error={info['error']}"))
        if not info["loaded"]:
            print("  ** Answer Relevance is running on the LEXICAL FALLBACK, which is a")
            print("     documented degradation, not an equal substitute. Fix this first.")

        rubric = load_rubric_for_question(db, q)
        print(f"rubric     : {rubric.source}")
        print()

        results = {}
        for label, text in (("AS WRITTEN", args.true_text), ("AS OCR'd", args.ocr_text)):
            results[label] = essay_grader.grade_answer(
                text, q, max_points=float(q.points or 0), rubric=rubric
            )

        # Per-criterion comparison. A grader that is working will show the
        # content criteria (relevance, key ideas) collapsing on OCR text while
        # the format criteria (structure) barely move -- structure judges
        # shape, which survives transcription damage.
        a, b = results["AS WRITTEN"], results["AS OCR'd"]
        print(f"{'criterion':<26} {'written':>9} {'ocr':>9} {'lost':>9}")
        print("-" * 56)
        bkeys = {c["key"]: c for c in b["criteria"]}
        for c in a["criteria"]:
            other = bkeys.get(c["key"], {})
            v1, v2 = c.get("value", 0), other.get("value", 0)
            print(f"{c['name']:<26} {v1:>8.1%} {v2:>8.1%} {v1 - v2:>8.1%}")

        print("-" * 56)
        print(f"{'SCORE':<26} {a['score']:>8.2f} {b['score']:>8.2f} "
              f"{a['score'] - b['score']:>8.2f}")
        print(f"{'PERCENTAGE':<26} {a['percentage']:>8.1%} {b['percentage']:>8.1%} "
              f"{a['percentage'] - b['percentage']:>8.1%}")

        print()
        print("--- READING THIS ---")
        gap = a["score"] - b["score"]
        if a["percentage"] < 0.5:
            print("The correctly-transcribed answer ALSO scored low. That points at the")
            print("grader or the rubric, not the OCR -- check the answer key and the")
            print("key_concepts/keywords on this question first.")
        elif gap > (float(q.points or 0) * 0.3):
            print(f"The grader scores the real answer {a['score']:.2f}/{q.points} and the OCR")
            print(f"transcription {b['score']:.2f}/{q.points}. The engine is working; the")
            print(f"{gap:.2f}-point gap is transcription loss, not grading error.")
            print()
            print("This number is worth reporting directly: it is the measured cost of")
            print("OCR error on the final grade, which is what justifies the professor")
            print("override interface existing at all.")
        else:
            print("Both scores are close, so OCR damage is not currently costing much")
            print("on this answer. Check the criteria table above for which ones moved.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
