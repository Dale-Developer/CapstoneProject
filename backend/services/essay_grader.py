"""ESSCAN essay grading engine.

Turns one OCR'd handwritten answer into a score plus a fully auditable
breakdown, using the rubric the professor configured for that specific
question.

Grading flow
------------
    student answer -> OCR text
                   -> spaCy linguistic evidence
                    + Sentence-BERT semantic relevance
                    + concept / requirement matching
                   -> criterion scores (0..1)
                   -> professor's rubric weights
                   -> weighted sum -> percentage -> question points

Sentence-BERT contributes the Answer Relevance criterion. It is one input to
the rubric, never the whole score.

Every criterion reports its configured weight, its own score and its weighted
contribution, and the final percentage is exactly the sum of the
contributions, so the professor UI can never display a weighting that differs
from the one used.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from services import nlp_spacy
from services.rubric import CRITERIA, ResolvedRubric, build_rubric
from services.runtime import env_float

logger = logging.getLogger("esscan.grader")

CRITERION_COLORS = {
    "semantic_relevance": "#5B8DEF",
    "concept_coverage": "#4CD787",
    "requirement_fulfillment": "#F5C842",
    "writing_quality": "#FF8A3D",
    "structure": "#D670E0",
    "keyword_terminology": "#F4645C",
}

# Expected response formats and the word bands that fit them.
#
#   (minimum_acceptable, ideal_minimum, ideal_maximum)
#
# These describe FORMAT FIT, not quality. An answer inside its band scores
# full marks for Structure whether it is 30 words or 150. Length is not used
# as a proxy for correctness anywhere else in the engine — the content
# criteria (relevance, concepts, requirements) judge that independently, so a
# short but correct answer is not penalised for being short.
FORMAT_BANDS: dict[str, tuple[int, int, int]] = {
    "one_word": (1, 1, 5),
    "one_sentence": (3, 4, 35),
    "few_sentences": (8, 12, 110),
    "one_paragraph": (18, 30, 200),
    "multi_paragraph": (50, 80, 500),
    "essay": (90, 130, 1200),
}

# Formats that imply more than one sentence, used for a light secondary check.
FORMAT_MIN_SENTENCES: dict[str, int] = {
    "one_word": 0,
    "one_sentence": 1,
    "few_sentences": 2,
    "one_paragraph": 2,
    "multi_paragraph": 5,
    "essay": 7,
}

VALID_FORMATS = tuple(FORMAT_BANDS.keys())

# How far below full marks a Structure score can fall for a non-empty answer
# that is merely outside its band. Structure judges format fit, so it should
# nudge rather than dominate.
STRUCTURE_FLOOR = 0.55
# Going over the ideal maximum is a minor style issue, not an error.
STRUCTURE_VERBOSE_FLOOR = 0.80


def parse_json_list(raw: Any) -> list[str]:
    """Parse a key_concepts/keywords/requirements column into a clean list.

    Stored as JSON text, but older rows may hold a plain comma-separated
    string, so both are accepted.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return [x.strip() for x in text.split(",") if x.strip()]
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()]
    if isinstance(parsed, str):
        return [x.strip() for x in parsed.split(",") if x.strip()]
    return []


# Backwards-compatible alias; earlier code imported this name.
_json_list = parse_json_list


def normalize_format(value: Any) -> str:
    fmt = str(value or "").strip().lower()
    return fmt if fmt in FORMAT_BANDS else "one_paragraph"


# ---------------------------------------------------------------------------
# Individual criterion scorers
# ---------------------------------------------------------------------------

def _score_writing_quality(analysis: nlp_spacy.Analysis) -> tuple[float, dict[str, Any]]:
    """Grammar-weighted writing quality with deliberately limited spelling influence.

    Spelling is folded in here rather than standing alone because these are
    OCR transcriptions of handwriting: a flagged word is at least as likely to
    be a recognition error as a student mistake. Its share of this criterion
    is capped (default 25%), and words that look like OCR damage to a term the
    professor supplied are excluded upstream in nlp_spacy.
    """
    if not analysis.word_count:
        return 0.0, {"grammarScore": 0.0, "flags": [], "spellingCounted": False}

    penalty = 0.0
    for flag in analysis.grammar_flags or []:
        if "run-on" in flag:
            penalty += 0.18
        elif "missing end punctuation" in flag:
            penalty += 0.12
        elif "not capitalised" in flag:
            penalty += 0.08
        elif "verb" in flag:
            penalty += 0.22
    if analysis.word_count < 6:
        # A fragment cannot demonstrate grammatical control, but this is a
        # nudge rather than a cliff — short answers are handled by Structure.
        penalty += 0.15

    grammar = max(0.0, min(1.0, 1.0 - penalty))

    spelling_share = env_float("ESSAY_SPELLING_SHARE", 0.25, 0.0, 0.5)
    detail: dict[str, Any] = {
        "grammarScore": round(grammar, 4),
        "flags": analysis.grammar_flags or [],
        "spellingCounted": bool(analysis.spelling_measurable),
        "spellingShare": round(spelling_share, 2),
        "misspelledCount": len(analysis.misspelled or []),
        "misspelledSample": (analysis.misspelled or [])[:12],
        "ocrLikelyCount": len(getattr(analysis, "ocr_suspected", None) or []),
        "ocrLikelySample": (getattr(analysis, "ocr_suspected", None) or [])[:12],
    }

    if not analysis.spelling_measurable:
        detail["note"] = "Spelling was not scored (no dictionary available); grammar only."
        return grammar, detail

    value = grammar * (1.0 - spelling_share) + analysis.spelling_ratio * spelling_share
    detail["spellingScore"] = round(analysis.spelling_ratio, 4)
    return max(0.0, min(1.0, value)), detail


def _score_structure(analysis: nlp_spacy.Analysis, expected_format: str) -> tuple[float, dict[str, Any]]:
    """How well the answer fits the professor's chosen response format."""
    fmt = normalize_format(expected_format)
    minimum, ideal_min, ideal_max = FORMAT_BANDS[fmt]
    words = analysis.word_count

    detail: dict[str, Any] = {
        "expectedFormat": fmt,
        "wordCount": words,
        "sentenceCount": analysis.sentence_count,
        "idealWordRange": [ideal_min, ideal_max],
        "minimumWords": minimum,
    }

    if not words:
        detail["verdict"] = "empty"
        return 0.0, detail

    if words < minimum:
        # Far too short for the requested format.
        length_score = 0.2 + 0.35 * (words / max(1, minimum))
        detail["verdict"] = "far below the expected length for this format"
    elif words < ideal_min:
        # Short but plausible: scale between the floor and full marks.
        span = max(1, ideal_min - minimum)
        length_score = STRUCTURE_FLOOR + (1.0 - STRUCTURE_FLOOR) * ((words - minimum) / span)
        detail["verdict"] = "slightly shorter than expected for this format"
    elif words <= ideal_max:
        length_score = 1.0
        detail["verdict"] = "fits the expected format"
    else:
        # Longer than expected is a minor style issue only.
        overflow = min(1.0, (words - ideal_max) / max(1, ideal_max))
        length_score = 1.0 - (1.0 - STRUCTURE_VERBOSE_FLOOR) * overflow
        detail["verdict"] = "longer than the expected format"

    min_sentences = FORMAT_MIN_SENTENCES.get(fmt, 0)
    if min_sentences:
        sentence_score = min(1.0, analysis.sentence_count / min_sentences)
        detail["minimumSentences"] = min_sentences
    else:
        sentence_score = 1.0

    value = 0.75 * length_score + 0.25 * sentence_score
    detail["lengthScore"] = round(length_score, 4)
    detail["sentenceScore"] = round(sentence_score, 4)
    return max(0.0, min(1.0, value)), detail


def _score_concept_coverage(
    analysis: nlp_spacy.Analysis,
    key_concepts: list[str],
    keywords: list[str],
) -> tuple[float, dict[str, Any]]:
    """Key-idea coverage, with keywords as supporting (not separate) evidence.

    Keywords contribute a minority share here instead of consuming their own
    slice of the final score, which is what "Keyword/Terminology is not a
    mandatory standalone criterion" means in practice.
    """
    concept_match = nlp_spacy.match_terms(analysis, key_concepts)
    detail: dict[str, Any] = {
        "concepts": {
            "total": concept_match["total"],
            "matched": concept_match["matched"],
            "hits": concept_match["hits"],
            "misses": concept_match["misses"],
        },
    }

    value = float(concept_match["ratio"])

    if keywords:
        keyword_match = nlp_spacy.match_terms(analysis, keywords)
        support = env_float("ESSAY_KEYWORD_SUPPORT_SHARE", 0.20, 0.0, 0.5)
        value = value * (1.0 - support) + float(keyword_match["ratio"]) * support
        detail["supportingKeywords"] = {
            "total": keyword_match["total"],
            "matched": keyword_match["matched"],
            "hits": keyword_match["hits"],
            "misses": keyword_match["misses"],
            "share": round(support, 2),
            "note": "Keywords support Key Ideas; they are not scored separately.",
        }

    return max(0.0, min(1.0, value)), detail


# Words that appear in a requirement because it is phrased as an instruction
# to the student, not because the student must write them. "Give at least one
# example" is satisfied by an example, not by the word "give".
INSTRUCTION_WORDS = {
    "give", "provide", "include", "state", "mention", "explain", "describe",
    "discuss", "list", "identify", "define", "name", "write", "show",
    "at", "least", "one", "two", "three", "must", "should", "your", "answer",
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "with", "about",
    "atleast", "students", "student", "please", "briefly", "clearly",
}


def _score_requirements(
    analysis: nlp_spacy.Analysis,
    requirements: list[str],
) -> tuple[float, dict[str, Any]]:
    """How many of the question's requirements the answer actually satisfies.

    Requirements are free-text instructions, so treating them as keyword
    lists does not work: "give at least one example" would look for the word
    "give". Instruction verbs and filler are stripped first, leaving the
    substantive content words, and a requirement counts as met when most of
    those appear in the answer.
    """
    if not requirements:
        return 1.0, {"total": 0, "matched": 0, "results": []}

    threshold = env_float("ESSAY_REQUIREMENT_THRESHOLD", 0.5, 0.1, 1.0)
    answer_lemmas = set(analysis.lemmas or [])
    results: list[dict[str, Any]] = []
    met = 0.0

    for requirement in requirements:
        probe = nlp_spacy.analyze(requirement)
        content = [
            lemma for lemma in (probe.content_lemmas or [])
            if lemma not in INSTRUCTION_WORDS
        ]

        if not content:
            # Nothing substantive to look for (e.g. "answer clearly"). Judged
            # by the other criteria rather than guessed at here.
            results.append({
                "requirement": requirement,
                "met": True,
                "coverage": 1.0,
                "note": "No specific content words to check; not scored against.",
            })
            met += 1.0
            continue

        present = [lemma for lemma in content if lemma in answer_lemmas]
        coverage = len(present) / len(content)
        is_met = coverage >= threshold
        # Partial credit rather than all-or-nothing, so a requirement that is
        # half-addressed is not scored the same as one ignored entirely.
        met += 1.0 if is_met else coverage
        results.append({
            "requirement": requirement,
            "met": is_met,
            "coverage": round(coverage, 3),
            "matchedTerms": present,
            "missingTerms": [lemma for lemma in content if lemma not in answer_lemmas],
        })

    ratio = met / len(requirements)
    return max(0.0, min(1.0, ratio)), {
        "total": len(requirements),
        "matched": sum(1 for r in results if r["met"]),
        "threshold": threshold,
        "results": results,
    }


def _score_keyword_terminology(analysis: nlp_spacy.Analysis, keywords: list[str]) -> tuple[float, dict[str, Any]]:
    """Only used when a legacy rubric explicitly configured this criterion."""
    match = nlp_spacy.match_terms(analysis, keywords)
    return float(match["ratio"]), {
        "total": match["total"],
        "matched": match["matched"],
        "hits": match["hits"],
        "misses": match["misses"],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def grade_answer(
    answer_text: str,
    question: Any,
    max_points: float | None = None,
    rubric: ResolvedRubric | None = None,
    precomputed_similarity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Grade one essay answer against one ExamQuestion using its rubric.

    ``rubric`` should be the result of
    ``services.rubric.load_rubric_for_question(db, question)``. When omitted,
    the system default is used — callers in the submission pipeline always
    pass the real one.

    ``precomputed_similarity`` lets a caller grading several essay questions
    for one submission batch-encode all of them in a single Sentence-BERT
    call (see ``nlp_spacy.batch_semantic_similarity``) and hand each result
    in here, instead of this function computing its own single-pair
    similarity. When omitted, the similarity is computed the same way it
    always was — this parameter is purely an optional speed path.
    """
    from services import rubric as rubric_module

    text = nlp_spacy.normalize(answer_text)
    points = float(max_points if max_points is not None else (question.points or 0) or 0)

    answer_key = str(getattr(question, "answer_key", "") or "")
    key_concepts = parse_json_list(getattr(question, "key_concepts", None))
    keywords = parse_json_list(getattr(question, "keywords", None))
    requirements = parse_json_list(getattr(question, "requirements", None))
    expected_format = normalize_format(getattr(question, "expected_response_format", None))

    if rubric is None:
        rubric = build_rubric(rubric_module.DEFAULT_RUBRIC, "system_default")

    # OCR context: terms the professor supplied. nlp_spacy uses these to avoid
    # flagging OCR damage to a domain term as a student spelling error.
    ocr_context = [answer_key] + key_concepts + keywords + requirements
    analysis = nlp_spacy.analyze(text, ocr_context=ocr_context)

    is_blank = not text or analysis.word_count == 0

    # ---- Which configured criteria can actually be evaluated? -------------
    # Missing evidence is never silently redistributed without a trace: the
    # criterion is marked unavailable with a reason, the adjustment is
    # reported, and exam creation validates for this case up front.
    available: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for entry in rubric.entries:
        reason = rubric_module.missing_evidence(entry["key"], question)
        if reason:
            unavailable.append({**entry, "unavailableReason": reason})
        else:
            available.append(entry)

    rubric_adjusted = bool(unavailable)
    fallback_note = None

    if not available:
        # Every configured criterion lacks its input. Documented deterministic
        # fallback: grade on the two criteria that need no professor-supplied
        # evidence, weighted evenly.
        available = [
            {**{k: v for k, v in e.items()}, "weight": 0.5, "configuredWeight": 50.0}
            for e in (
                _synthetic_entry("writing_quality"),
                _synthetic_entry("structure"),
            )
        ]
        fallback_note = (
            "None of the configured criteria could be evaluated because the question is "
            "missing its answer key, key concepts and requirements. Graded on Writing "
            "Quality and Organization and Structure only."
        )

    total_available_weight = sum(e["weight"] for e in available) or 1.0

    # ---- Score each available criterion -----------------------------------
    scored: list[dict[str, Any]] = []
    percentage = 0.0

    for entry in available:
        key = entry["key"]

        if is_blank:
            value, detail = 0.0, {}
        elif key == "semantic_relevance":
            similarity = (
                precomputed_similarity
                if precomputed_similarity is not None
                else nlp_spacy.semantic_similarity(analysis, answer_key)
            )
            value = float(similarity.get("score") or 0.0)
            detail = {
                "engine": similarity.get("engine"),
                "model": similarity.get("model"),
                "pending": bool(similarity.get("pending")),
                "note": similarity.get("note") or similarity.get("error"),
            }
        elif key == "concept_coverage":
            value, detail = _score_concept_coverage(analysis, key_concepts, keywords)
        elif key == "requirement_fulfillment":
            value, detail = _score_requirements(analysis, requirements)
        elif key == "writing_quality":
            value, detail = _score_writing_quality(analysis)
        elif key == "structure":
            value, detail = _score_structure(analysis, expected_format)
        elif key == "keyword_terminology":
            value, detail = _score_keyword_terminology(analysis, keywords)
        else:
            value, detail = 0.0, {"note": f"Unknown criterion '{key}' was skipped."}

        # Effective weight is the configured weight renormalised over the
        # criteria that could be evaluated. With a complete question it equals
        # the configured weight.
        effective = entry["weight"] / total_available_weight
        contribution = value * effective
        percentage += contribution

        scored.append({
            "key": key,
            "name": entry["name"],
            "label": entry["label"],
            "color": CRITERION_COLORS.get(key, "#5B8DEF"),
            "implementation": entry.get("implementation"),
            "configuredWeight": entry["configuredWeight"],
            "weight": round(entry["weight"], 4),
            "effectiveWeight": round(effective, 4),
            "value": round(value, 4),
            # Percentage points this criterion contributes to the final score.
            "contribution": round(contribution * 100, 2),
            "counted": True,
            "detail": detail,
        })

    for entry in unavailable:
        scored.append({
            "key": entry["key"],
            "name": entry["name"],
            "label": entry["label"],
            "color": CRITERION_COLORS.get(entry["key"], "#94A3B8"),
            "implementation": entry.get("implementation"),
            "configuredWeight": entry["configuredWeight"],
            "weight": round(entry["weight"], 4),
            "effectiveWeight": 0.0,
            "value": None,
            "contribution": 0.0,
            "counted": False,
            "unavailableReason": (
                f"This question has no {entry['unavailableReason']}, so "
                f"{entry['label']} cannot be evaluated. Its {entry['configuredWeight']:g}% "
                f"was redistributed across the remaining criteria."
            ),
            "detail": {},
        })

    percentage = max(0.0, min(1.0, percentage))
    score = round(percentage * points, 2)

    similarity_engine = next(
        (c["detail"].get("engine") for c in scored
         if c["key"] == "semantic_relevance" and c["counted"]),
        None,
    )
    semantic_pending = next(
        (bool(c["detail"].get("pending")) for c in scored
         if c["key"] == "semantic_relevance" and c["counted"]),
        False,
    )

    return {
        "score": score,
        "maxScore": round(points, 2),
        "percentage": round(percentage, 4),
        "isBlank": is_blank,
        "criteria": scored,
        "analysis": analysis.to_dict(),
        # ---- Audit trail --------------------------------------------------
        "rubric": {
            "source": rubric.source,
            "adjusted": rubric_adjusted,
            "fallbackNote": fallback_note,
            "unknownCriteria": rubric.unknown_names,
            "configured": [
                {"name": e["name"], "label": e["label"], "weight": e["configuredWeight"]}
                for e in rubric.entries
            ],
        },
        "semanticPending": semantic_pending,
        "engine": {
            "nlp": analysis.engine,
            "similarity": similarity_engine or "not_configured",
            "sbert": nlp_spacy.sbert_info(),
        },
        "expectedResponseFormat": expected_format,
        "summary": _summary(scored, analysis, is_blank),
    }


def _synthetic_entry(key: str) -> dict[str, Any]:
    crit = CRITERIA[key]
    return {
        "key": key,
        "name": crit.technical_name,
        "label": crit.label,
        "description": crit.description,
        "implementation": crit.implementation,
        "configuredWeight": 0.0,
        "weight": 0.0,
    }


def _summary(scored: list[dict[str, Any]], analysis, is_blank: bool) -> str:
    """One line the professor can read without opening the breakdown."""
    if is_blank:
        return "No answer text was detected for this question."

    parts = []
    for c in scored:
        if not c["counted"]:
            continue
        if c["key"] == "concept_coverage":
            d = c["detail"].get("concepts") or {}
            if d.get("total"):
                parts.append(f"{d['matched']}/{d['total']} key ideas")
        elif c["key"] == "requirement_fulfillment":
            if c["detail"].get("total"):
                parts.append(f"{c['detail']['matched']}/{c['detail']['total']} requirements met")
        elif c["key"] == "semantic_relevance":
            parts.append(f"{round(c['value'] * 100)}% relevance")

    parts.append(f"{analysis.word_count} words")
    if analysis.grammar_flags:
        parts.append(analysis.grammar_flags[0].lower())
    return "; ".join(parts) + "."


def highlight_spans(answer_text: str, question: Any) -> list[dict[str, Any]]:
    """Locate matched concepts/keywords in the answer for UI underlining."""
    text = str(answer_text or "")
    if not text.strip():
        return []

    lowered = text.lower()
    spans: list[dict[str, Any]] = []

    def add(terms: list[str], reason: str, color: str) -> None:
        for term in terms:
            needle = nlp_spacy.normalize(term).lower()
            if not needle:
                continue
            start = lowered.find(needle)
            if start < 0:
                continue
            spans.append({
                "start": start,
                "end": start + len(needle),
                "text": text[start:start + len(needle)],
                "reason": reason,
                "color": color,
            })

    add(parse_json_list(getattr(question, "key_concepts", None)),
        "Key idea match", CRITERION_COLORS["concept_coverage"])
    add(parse_json_list(getattr(question, "keywords", None)),
        "Supporting term match", CRITERION_COLORS["keyword_terminology"])

    spans.sort(key=lambda s: (s["start"], -s["end"]))
    cleaned: list[dict[str, Any]] = []
    last_end = -1
    for span in spans:
        if span["start"] >= last_end:
            cleaned.append(span)
            last_end = span["end"]
    return cleaned


__all__ = [
    "FORMAT_BANDS",
    "VALID_FORMATS",
    "grade_answer",
    "highlight_spans",
    "normalize_format",
    "parse_json_list",
]
