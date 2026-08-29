"""ESSCAN spaCy NLP layer for essay analysis.

Scope and boundaries
--------------------
This module owns the *linguistic* half of essay grading:

- tokenisation, lemmatisation, sentence segmentation
- keyword and key-concept detection (lemma-aware, not raw substring)
- surface quality signals: spelling, basic grammar plausibility, structure
- a lexical similarity score used **only as a placeholder**

Semantic similarity is deliberately NOT finished here. The fine-tuned
Sentence-BERT model is still being trained, so ``semantic_similarity()``
currently falls back to a lexical measure and reports
``engine="lexical_fallback"``. When the SBERT checkpoint is ready, implement
``_sbert_encode()`` (see the SENTENCE-BERT SEAM section) and everything
downstream — the grader, the API, the professor UI — picks it up without any
other change, because the returned shape is already the final one.

The module never raises: if spaCy or its model is missing, every function
degrades to a regex/heuristic implementation so grading still produces a
score and the professor can still override it.
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from services.runtime import TTLValue, env_bool, env_float, env_int

logger = logging.getLogger("esscan.nlp")

SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_sm")

_nlp = None
_nlp_error: str | None = None
_nlp_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Spelling
# ---------------------------------------------------------------------------
# spaCy's ``token.is_oov`` is NOT a spellchecker. The small English model
# ships with zero word vectors, so ``is_oov`` returns True for every single
# token including "the" and "water". Using it as a spelling signal — as this
# module originally did — scored a perfectly written answer at 44% spelling.
#
# The real check uses pyspellchecker when it is installed. If it is not, the
# spelling criterion reports itself as unmeasurable and the grader drops it
# and redistributes its weight, which is far better than inventing a number.

_speller = None
_speller_ready = False
_speller_lock = threading.Lock()


def _get_speller():
    global _speller, _speller_ready
    if _speller_ready:
        return _speller
    with _speller_lock:
        if _speller_ready:
            return _speller
        try:
            from spellchecker import SpellChecker

            _speller = SpellChecker(distance=1)
        except Exception as exc:
            logger.info("pyspellchecker unavailable, spelling will not be scored: %s", exc)
            _speller = None
        _speller_ready = True
        return _speller


def spelling_available() -> bool:
    return _get_speller() is not None


def _find_misspelled(
    words: list[str],
    domain_terms: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Split unknown words into likely student errors and likely OCR damage.

    These are transcriptions of handwriting, so an unknown word is at least as
    likely to be an OCR error as a spelling mistake. When an unknown word is a
    near-match for a term the professor supplied (answer key, key concepts,
    keywords, requirements), it is treated as OCR damage and excluded from the
    spelling penalty — "decompsers" against an expected "decomposers" should
    not cost the student marks.

    Returns ``(misspelled, ocr_suspected)``.
    """
    speller = _get_speller()
    if speller is None or not words:
        return [], []
    candidates = [w for w in words if w.isalpha() and len(w) > 3]
    if not candidates:
        return [], []
    try:
        unknown = speller.unknown(candidates)
    except Exception:
        return [], []

    domain_terms = domain_terms or set()
    threshold = env_float("NLP_OCR_LENIENCY_THRESHOLD", 0.78, 0.5, 1.0)

    misspelled: list[str] = []
    ocr_suspected: list[str] = []
    seen: set[str] = set()

    for word in candidates:
        if word not in unknown or word in seen:
            continue
        seen.add(word)

        looks_like_ocr = False
        for term in domain_terms:
            if abs(len(term) - len(word)) > 3:
                continue
            if _ratio(term, word) >= threshold:
                looks_like_ocr = True
                break

        (ocr_suspected if looks_like_ocr else misspelled).append(word)

    return misspelled, ocr_suspected


def _domain_term_set(ocr_context) -> set[str]:
    """Flatten professor-supplied text into a set of comparable lowercase words."""
    terms: set[str] = set()
    for item in ocr_context or []:
        for token in re.findall(r"[a-zA-Z]{4,}", str(item or "")):
            terms.add(token.lower())
    return terms

# Words that carry no topical meaning and must never count as a "concept hit".
_FALLBACK_STOPWORDS = {
    "a", "about", "above", "after", "again", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "did", "do", "does",
    "doing", "down", "during", "each", "few", "for", "from", "further", "had",
    "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only",
    "or", "other", "our", "out", "over", "own", "same", "she", "should", "so",
    "some", "such", "than", "that", "the", "their", "theirs", "them", "then",
    "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "whom", "why", "will", "with", "would", "you",
    "your", "yours",
}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _load_nlp():
    """Load spaCy lazily and only once.

    The parser and NER components are disabled: essay scoring needs the
    tagger, lemmatiser and sentence boundaries, and dropping the rest cuts
    per-document processing time by roughly half on CPU.
    """
    global _nlp, _nlp_error

    if _nlp is not None or _nlp_error is not None:
        return _nlp

    with _nlp_lock:
        if _nlp is not None or _nlp_error is not None:
            return _nlp
        try:
            import spacy
        except ImportError:
            _nlp_error = (
                "spaCy is not installed. Run: python -m pip install spacy"
            )
            return None

        disable = [
            x.strip() for x in os.getenv("SPACY_DISABLE", "parser,ner").split(",")
            if x.strip()
        ]
        try:
            nlp = spacy.load(SPACY_MODEL, disable=disable)
        except OSError:
            _nlp_error = (
                f"The spaCy model '{SPACY_MODEL}' is not downloaded. Run: "
                f"python -m spacy download {SPACY_MODEL}"
            )
            return None
        except Exception as exc:
            _nlp_error = f"{type(exc).__name__}: {exc}"
            return None

        # `parser` is disabled, so add the cheap rule-based sentence splitter.
        if "parser" in disable and "senter" not in nlp.pipe_names:
            try:
                nlp.add_pipe("sentencizer")
            except Exception:
                pass

        nlp.max_length = env_int("SPACY_MAX_LENGTH", 200_000, 10_000, 2_000_000)
        _nlp = nlp
        _nlp_error = None
        return _nlp


def spacy_available() -> bool:
    return _load_nlp() is not None


def spacy_error() -> str | None:
    _load_nlp()
    return _nlp_error


def warmup() -> str:
    """Load the model and push one short document through the pipeline."""
    nlp = _load_nlp()
    if nlp is None:
        return f"unavailable: {_nlp_error}"
    try:
        nlp("The biosphere supports life on Earth.")
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"
    return f"ready ({SPACY_MODEL})"


# ---------------------------------------------------------------------------
# Text utilities (always available, spaCy or not)
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _simple_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", normalize(text).lower())


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# Document analysis
# ---------------------------------------------------------------------------

class Analysis:
    """Everything the grader needs from one piece of student text."""

    __slots__ = (
        "text", "tokens", "lemmas", "content_lemmas", "sentences",
        "word_count", "sentence_count", "unique_ratio", "avg_sentence_length",
        "misspelled", "spelling_ratio", "grammar_flags", "engine", "pos_counts",
        "spelling_measurable", "ocr_suspected",
    )

    def __init__(self, **kwargs):
        for key in self.__slots__:
            setattr(self, key, kwargs.get(key))

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "wordCount": self.word_count,
            "sentenceCount": self.sentence_count,
            "uniqueWordRatio": round(self.unique_ratio, 4),
            "averageSentenceLength": round(self.avg_sentence_length, 2),
            "misspelledCount": len(self.misspelled or []),
            "misspelledSample": (self.misspelled or [])[:12],
            "spellingRatio": round(self.spelling_ratio, 4),
            "spellingMeasurable": bool(self.spelling_measurable),
            "ocrSuspectedCount": len(self.ocr_suspected or []),
            "ocrSuspectedSample": (self.ocr_suspected or [])[:12],
            "grammarFlags": self.grammar_flags or [],
            "posCounts": self.pos_counts or {},
        }


def analyze(text: str, ocr_context=None) -> Analysis:
    """Run the full linguistic analysis on one answer.

    ``ocr_context`` is any professor-supplied text for the question (answer
    key, key concepts, keywords, requirements). It is used only to recognise
    OCR damage to domain terms so those are not charged as spelling errors.
    """
    clean = normalize(text)
    domain_terms = _domain_term_set(ocr_context)
    nlp = _load_nlp()

    if nlp is None:
        return _analyze_fallback(clean, domain_terms)

    try:
        doc = nlp(clean[: nlp.max_length])
    except Exception as exc:
        logger.warning("spaCy processing failed, using fallback: %s", exc)
        return _analyze_fallback(clean)

    tokens: list[str] = []
    lemmas: list[str] = []
    content_lemmas: list[str] = []
    spell_candidates: list[str] = []
    pos_counts: Counter = Counter()

    for token in doc:
        if token.is_space or token.is_punct:
            continue
        lower = token.lower_
        tokens.append(lower)
        lemma = (token.lemma_ or lower).lower()
        lemmas.append(lemma)
        pos_counts[token.pos_] += 1

        if not token.is_stop and token.is_alpha and len(lower) > 2:
            content_lemmas.append(lemma)

        # Proper nouns are excluded: an exam answer legitimately contains
        # names and domain terms that no general dictionary knows, and
        # penalising those would punish the strongest answers hardest.
        if token.is_alpha and not token.like_num and token.pos_ != "PROPN":
            spell_candidates.append(lower)

    sentences = [s.text.strip() for s in doc.sents if s.text.strip()]
    if not sentences and clean:
        sentences = [clean]

    word_count = len(tokens)
    unique_ratio = (len(set(lemmas)) / word_count) if word_count else 0.0
    avg_sentence_length = (word_count / len(sentences)) if sentences else 0.0

    spelling_measurable = spelling_available()
    if spelling_measurable:
        misspelled, ocr_suspected = _find_misspelled(spell_candidates, domain_terms)
    else:
        misspelled, ocr_suspected = [], []
    checked = len([w for w in spell_candidates if w.isalpha() and len(w) > 3])
    if spelling_measurable and checked:
        # Words attributed to OCR damage are excluded from the penalty.
        spelling_ratio = 1.0 - (len(misspelled) / checked)
    else:
        spelling_ratio = 0.0

    return Analysis(
        text=clean,
        tokens=tokens,
        lemmas=lemmas,
        content_lemmas=content_lemmas,
        sentences=sentences,
        word_count=word_count,
        sentence_count=len(sentences),
        unique_ratio=unique_ratio,
        avg_sentence_length=avg_sentence_length,
        misspelled=misspelled,
        spelling_ratio=max(0.0, min(1.0, spelling_ratio)),
        spelling_measurable=spelling_measurable and bool(checked),
        ocr_suspected=ocr_suspected,
        grammar_flags=_grammar_flags(sentences, pos_counts, word_count),
        engine=f"spacy:{SPACY_MODEL}",
        pos_counts=dict(pos_counts),
    )


def _analyze_fallback(clean: str, domain_terms: set[str] | None = None) -> Analysis:
    tokens = _simple_tokens(clean)
    fb_misspelled, fb_ocr = (
        _find_misspelled(tokens, domain_terms) if spelling_available() else ([], [])
    )
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
    word_count = len(tokens)
    content = [t for t in tokens if t not in _FALLBACK_STOPWORDS and len(t) > 2]
    return Analysis(
        text=clean,
        tokens=tokens,
        lemmas=tokens,
        content_lemmas=content,
        sentences=sentences or ([clean] if clean else []),
        word_count=word_count,
        sentence_count=len(sentences),
        unique_ratio=(len(set(tokens)) / word_count) if word_count else 0.0,
        avg_sentence_length=(word_count / len(sentences)) if sentences else 0.0,
        misspelled=fb_misspelled,
        ocr_suspected=fb_ocr,
        spelling_ratio=(
            1.0 - (len(fb_misspelled) / max(1, len([t for t in tokens if len(t) > 3])))
            if spelling_available() and word_count else 0.0
        ),
        spelling_measurable=spelling_available() and bool(word_count),
        grammar_flags=_grammar_flags(sentences, Counter(), word_count),
        engine="heuristic_fallback",
        pos_counts={},
    )


def _grammar_flags(sentences: Sequence[str], pos_counts: Counter, word_count: int) -> list[str]:
    """Cheap, explainable grammar signals.

    This is intentionally not a full grammar checker. It surfaces the handful
    of issues that actually appear in scanned handwritten answers and that a
    professor would accept as justification for a deduction.
    """
    flags: list[str] = []
    if not sentences:
        return flags

    long_sentences = sum(1 for s in sentences if len(_simple_tokens(s)) > 45)
    if long_sentences:
        flags.append(f"{long_sentences} run-on sentence(s) over 45 words")

    unpunctuated = sum(1 for s in sentences if not re.search(r"[.!?]\s*$", s.strip()))
    if unpunctuated > 1:
        flags.append(f"{unpunctuated} sentence(s) missing end punctuation")

    lowercase_starts = sum(
        1 for s in sentences if s[:1].isalpha() and s[:1].islower()
    )
    if lowercase_starts:
        flags.append(f"{lowercase_starts} sentence(s) not capitalised")

    if pos_counts and word_count >= 12:
        verbs = pos_counts.get("VERB", 0) + pos_counts.get("AUX", 0)
        if verbs == 0:
            flags.append("No finite verb detected")
        elif verbs / max(1, len(sentences)) < 0.6:
            flags.append("Some sentences appear to lack a verb")

    return flags


# ---------------------------------------------------------------------------
# Keyword / key-concept matching
# ---------------------------------------------------------------------------

def _lemma_key(nlp, phrase: str) -> list[str]:
    phrase = normalize(phrase).lower()
    if not phrase:
        return []
    if nlp is None:
        return [t for t in _simple_tokens(phrase)]
    try:
        doc = nlp(phrase)
    except Exception:
        return _simple_tokens(phrase)
    return [
        (t.lemma_ or t.lower_).lower()
        for t in doc
        if not t.is_space and not t.is_punct
    ]


def match_terms(
    analysis: Analysis,
    terms: Iterable[str],
    fuzzy_threshold: float | None = None,
) -> dict[str, Any]:
    """Check which of ``terms`` appear in the student's answer.

    Matching is lemma-based, so "cycles nutrients" satisfies the expected
    keyword "nutrient cycling". Single-token terms additionally allow a fuzzy
    match, because OCR of handwriting routinely drops or doubles a letter and
    a professor would not want "decompsers" scored as a miss.
    """
    terms = [normalize(t) for t in (terms or []) if normalize(t)]
    if not terms:
        return {"total": 0, "matched": 0, "ratio": 1.0, "hits": [], "misses": []}

    threshold = (
        fuzzy_threshold
        if fuzzy_threshold is not None
        else env_float("NLP_FUZZY_MATCH_THRESHOLD", 0.86, 0.5, 1.0)
    )
    nlp = _load_nlp()
    answer_lemmas = list(analysis.lemmas or [])
    answer_set = set(answer_lemmas)
    answer_joined = " ".join(answer_lemmas)

    hits: list[dict[str, Any]] = []
    misses: list[str] = []

    for term in terms:
        term_lemmas = _lemma_key(nlp, term)
        if not term_lemmas:
            continue

        matched = False
        how = ""

        if len(term_lemmas) == 1:
            needle = term_lemmas[0]
            if needle in answer_set:
                matched, how = True, "lemma"
            else:
                # Fuzzy: only against tokens of a comparable length, so short
                # words cannot accidentally match everything.
                for candidate in answer_set:
                    if abs(len(candidate) - len(needle)) > 3:
                        continue
                    if _ratio(candidate, needle) >= threshold:
                        matched, how = True, f"fuzzy:{candidate}"
                        break
        else:
            phrase = " ".join(term_lemmas)
            if phrase in answer_joined:
                matched, how = True, "phrase"
            else:
                # Partial credit for a multi-word concept: most of its content
                # words present anywhere in the answer.
                content = [t for t in term_lemmas if t not in _FALLBACK_STOPWORDS]
                if content:
                    present = sum(1 for t in content if t in answer_set)
                    if present / len(content) >= env_float("NLP_PHRASE_PARTIAL", 0.75, 0.3, 1.0):
                        matched, how = True, "partial-phrase"

        if matched:
            hits.append({"term": term, "match": how})
        else:
            misses.append(term)

    total = len(hits) + len(misses)
    return {
        "total": total,
        "matched": len(hits),
        "ratio": (len(hits) / total) if total else 1.0,
        "hits": hits,
        "misses": misses,
    }


# ---------------------------------------------------------------------------
# SENTENCE-BERT (Answer Relevance)
# ---------------------------------------------------------------------------
# Production model: ESSCAN_AAA_SBERT_ASAP_V3 (score-aware ASAP fine-tune).
#
# Selected on the project's own evaluation. V3 beats the earlier STSB V1
# checkpoint and the stock baseline on every metric measured:
#
#   model                       MAE      RMSE     Pearson   Spearman
#   all-MiniLM-L6-v2            0.4563   0.6061   0.7134    0.7103
#   ESSCAN_AAA_SBERT_STSB_V1    0.4558   0.6044   0.7154    0.7131
#   ESSCAN_AAA_SBERT_ASAP_V2    0.4586   0.6069   0.7134    0.7116
#   ESSCAN_AAA_SBERT_ASAP_V3    0.4344   0.5758   0.7459    0.7404   <- selected
#
# CALIBRATION (important)
# -----------------------
# V3 was trained with CosineSimilarityLoss, so its cosine output is a
# prediction of the training label rather than a general-purpose similarity.
# In practice its useful band on exam answers is narrow and high:
#
#   completely unrelated text   ~0.70
#   wrong topic, same subject   ~0.87
#   vague but on topic          ~0.90
#   partially correct           ~0.94
#   fully correct               ~0.96 - 0.99
#
# Feeding the raw cosine (or the textbook (cos+1)/2 mapping) straight into a
# rubric would award roughly 70-85% relevance to an answer about basketball.
# The raw value is therefore rescaled from that operating band onto 0..1 via
# SBERT_SIMILARITY_FLOOR / SBERT_SIMILARITY_CEILING. The defaults are tuned
# for V3; a differently-calibrated model needs different values, and setting
# floor >= ceiling disables rescaling entirely.
#
# The path is configuration, never a hard-coded machine-specific location.
# If the model cannot be loaded the engine degrades to a lexical measure and
# says so: results are tagged engine="lexical_fallback" with pending=true.
#
# Enable with, in backend/.env:
#     SBERT_ENABLED=true
#     SBERT_MODEL_PATH=./ai_models/ESSCAN_AAA_SBERT_ASAP_V3_FINAL
# ---------------------------------------------------------------------------

DEFAULT_SBERT_PATH = "./ai_models/ESSCAN_AAA_SBERT_ASAP_V3_FINAL"

_sbert_model = None
_sbert_error: str | None = None
_sbert_loaded = False          # load attempted, regardless of outcome
_sbert_name: str | None = None
_sbert_lock = threading.Lock()


def sbert_enabled() -> bool:
    return env_bool("SBERT_ENABLED", False)


def sbert_model_path() -> str:
    """Resolve the configured model directory to the folder SentenceTransformer needs.

    The released checkpoint is packaged as
    ``ESSCAN_AAA_SBERT_ASAP_V3_FINAL/model/`` with the evaluation files
    alongside it, so pointing SBERT_MODEL_PATH at either the release folder or
    the inner ``model/`` folder works. Without this, aiming at the release
    folder would fail with a confusing "not a valid model" error.
    """
    path = os.getenv("SBERT_MODEL_PATH", DEFAULT_SBERT_PATH)
    if not os.path.isabs(path):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.abspath(os.path.join(backend_dir, path))

    if not os.path.isfile(os.path.join(path, "modules.json")):
        nested = os.path.join(path, "model")
        if os.path.isfile(os.path.join(nested, "modules.json")):
            return nested
    return path


def _calibrate_similarity(cosine: float) -> float:
    """Rescale the model's raw cosine onto a usable 0..1 grading range.

    See the CALIBRATION note above: V3's cosine for an exam answer sits
    between roughly 0.70 (unrelated) and 0.99 (fully correct), so the raw
    value would hand out large marks for irrelevant text.
    """
    floor = env_float("SBERT_SIMILARITY_FLOOR", 0.80, -1.0, 1.0)
    ceiling = env_float("SBERT_SIMILARITY_CEILING", 0.97, -1.0, 1.0)
    if ceiling <= floor:
        # Rescaling disabled; clamp the raw cosine instead.
        return max(0.0, min(1.0, cosine))
    return max(0.0, min(1.0, (cosine - floor) / (ceiling - floor)))


def _load_sbert():
    """Load the fine-tuned Sentence-BERT model once, if it is turned on."""
    global _sbert_model, _sbert_error, _sbert_loaded, _sbert_name

    if not sbert_enabled():
        _sbert_error = "Sentence-BERT is disabled (SBERT_ENABLED is not set)."
        return None

    # One load attempt per process: without this flag a failed load was
    # retried on every single answer, paying the import/disk cost each time.
    if _sbert_loaded:
        return _sbert_model

    with _sbert_lock:
        if _sbert_loaded:
            return _sbert_model
        _sbert_loaded = True

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            _sbert_error = (
                "sentence-transformers is not installed. Run: "
                "python -m pip install sentence-transformers"
            )
            logger.warning("Sentence-BERT unavailable: %s", _sbert_error)
            return None

        path = sbert_model_path()
        if not os.path.isdir(path):
            _sbert_error = f"No Sentence-BERT model directory at {path}."
            logger.warning("Sentence-BERT unavailable: %s", _sbert_error)
            return None

        try:
            _sbert_model = SentenceTransformer(path, device=os.getenv("SBERT_DEVICE", "cpu"))
            # Label with the release folder, not the inner "model" directory,
            # so the audit trail names the checkpoint the professor deployed.
            name = os.path.basename(path.rstrip("/\\"))
            if name.lower() in {"model", "."}:
                name = os.path.basename(os.path.dirname(path.rstrip("/\\")))
            _sbert_name = name or "sentence-bert"
            _sbert_error = None
            logger.info("Sentence-BERT loaded: %s", _sbert_name)
        except Exception as exc:
            _sbert_model = None
            _sbert_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Sentence-BERT failed to load: %s", _sbert_error)
        return _sbert_model


def sbert_ready() -> bool:
    return _load_sbert() is not None


def sbert_info() -> dict[str, Any]:
    """Audit record of which semantic engine is actually in use."""
    ready = sbert_ready()
    return {
        "enabled": sbert_enabled(),
        "loaded": ready,
        "model": _sbert_name if ready else None,
        "path": sbert_model_path() if sbert_enabled() else None,
        "error": None if ready else _sbert_error,
    }


def warmup_sbert() -> str:
    if not sbert_enabled():
        return "disabled"
    model = _load_sbert()
    if model is None:
        return f"unavailable: {_sbert_error}"
    try:
        model.encode(["warmup"], convert_to_numpy=True, show_progress_bar=False)
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"
    return f"ready ({_sbert_name})"


def _sbert_similarity(answer: str, reference: str):
    """Return ``(calibrated_score, raw_cosine)`` or None if unavailable."""
    model = _load_sbert()
    if model is None:
        return None
    try:
        import numpy as np

        vectors = model.encode(
            [answer, reference],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        cosine = float(np.dot(vectors[0], vectors[1]))
        return _calibrate_similarity(cosine), cosine
    except Exception as exc:
        logger.warning("Sentence-BERT similarity failed: %s", exc)
        return None


def _lexical_similarity(analysis: Analysis, reference: str) -> float:
    """Cosine similarity over content-lemma frequency vectors.

    Fallback only. It rewards reuse of the reference vocabulary, which
    correlates with — but is not — understanding.
    """
    ref_analysis = analyze(reference)
    a = Counter(analysis.content_lemmas or [])
    b = Counter(ref_analysis.content_lemmas or [])
    if not a or not b:
        return 0.0

    shared = set(a) & set(b)
    if not shared:
        return 0.0

    dot = sum(a[t] * b[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def semantic_similarity(analysis: Analysis, reference: str) -> dict[str, Any]:
    """Semantic relevance between a student's answer and the answer key.

    Returns ``{"score", "engine", "pending", "model"}``. ``engine`` is
    ``"sentence_transformer"`` when the real model produced the number and
    ``"lexical_fallback"`` otherwise; ``pending`` is True only in the fallback
    case, so the UI can label it honestly.
    """
    reference = normalize(reference)
    if not reference or not (analysis.text or "").strip():
        return {"score": 0.0, "engine": "none", "pending": False, "model": None}

    if sbert_enabled():
        result = _sbert_similarity(analysis.text, reference)
        if result is not None:
            score, cosine = result
            return {
                "score": score,
                # Raw cosine kept for auditability: it shows what the model
                # actually produced before calibration.
                "rawCosine": round(cosine, 4),
                "engine": "sentence_transformer",
                "pending": False,
                "model": _sbert_name,
            }
        return {
            "score": _lexical_similarity(analysis, reference),
            "engine": "lexical_fallback",
            "pending": True,
            "model": None,
            "error": _sbert_error,
            "note": "Sentence-BERT is enabled but could not be loaded; using a lexical measure.",
        }

    return {
        "score": _lexical_similarity(analysis, reference),
        "engine": "lexical_fallback",
        "pending": True,
        "model": None,
        "note": "Sentence-BERT is disabled (SBERT_ENABLED is not set).",
    }


def batch_semantic_similarity(
    pairs: list[tuple[Analysis, str]],
) -> list[dict[str, Any]]:
    """Semantic relevance for many (answer, reference) pairs in one pass.

    A submission with several essay questions previously called
    ``semantic_similarity()`` once per question, each paying its own
    ``model.encode()`` forward pass. SentenceTransformer's per-call overhead
    (tokenization, batching setup, and on GPU especially, kernel launch) is
    largely fixed regardless of batch size, so encoding every answer and
    reference for a submission in a single call is meaningfully faster than
    N separate calls — the saving scales with essay-question count and is
    largest on GPU, but is real even on CPU.

    Returns one result per input pair, in the same shape and order as
    ``semantic_similarity()`` would produce for each pair individually, so
    callers can use this as a drop-in batched replacement for a loop.
    """
    if not pairs:
        return []

    results: list[dict[str, Any] | None] = [None] * len(pairs)

    # Anything without real text on both sides never needed the model.
    fallback_indices: list[int] = []
    batch_indices: list[int] = []
    normalized_refs: list[str] = []
    for i, (analysis, reference) in enumerate(pairs):
        ref = normalize(reference)
        normalized_refs.append(ref)
        if not ref or not (analysis.text or "").strip():
            results[i] = {"score": 0.0, "engine": "none", "pending": False, "model": None}
        elif sbert_enabled():
            batch_indices.append(i)
        else:
            fallback_indices.append(i)

    if batch_indices:
        model = _load_sbert()
        if model is not None:
            try:
                import numpy as np

                # Flatten to [answer_0, ref_0, answer_1, ref_1, ...] so one
                # encode() call covers every pair; unzip the vectors back out.
                flat_texts: list[str] = []
                for i in batch_indices:
                    flat_texts.append(pairs[i][0].text)
                    flat_texts.append(normalized_refs[i])

                vectors = model.encode(
                    flat_texts,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=env_int("SBERT_BATCH_SIZE", 32, 1, 256),
                )
                for slot, i in enumerate(batch_indices):
                    answer_vec = vectors[slot * 2]
                    ref_vec = vectors[slot * 2 + 1]
                    cosine = float(np.dot(answer_vec, ref_vec))
                    results[i] = {
                        "score": _calibrate_similarity(cosine),
                        "rawCosine": round(cosine, 4),
                        "engine": "sentence_transformer",
                        "pending": False,
                        "model": _sbert_name,
                    }
            except Exception as exc:
                logger.warning("Batched Sentence-BERT similarity failed, falling back: %s", exc)
                fallback_indices.extend(i for i in batch_indices if results[i] is None)
        else:
            fallback_indices.extend(batch_indices)

    for i in fallback_indices:
        analysis, _ = pairs[i]
        results[i] = {
            "score": _lexical_similarity(analysis, normalized_refs[i]),
            "engine": "lexical_fallback",
            "pending": True,
            "model": None,
            "note": (
                "Sentence-BERT is enabled but could not be loaded; using a lexical measure."
                if sbert_enabled()
                else "Sentence-BERT is disabled (SBERT_ENABLED is not set)."
            ),
        }

    return results  # type: ignore[return-value]


def status() -> dict[str, Any]:
    """Diagnostics for the AI-services health endpoint."""
    return {
        "spacy": {
            "available": spacy_available(),
            "model": SPACY_MODEL,
            "error": spacy_error(),
        },
        "spelling": {
            "available": spelling_available(),
            "backend": "pyspellchecker" if spelling_available() else None,
            "note": None if spelling_available() else (
                "pyspellchecker is not installed, so the spelling criterion is "
                "excluded from grading instead of guessed."
            ),
        },
        "sentenceBert": sbert_info(),
    }


__all__ = [
    "Analysis",
    "analyze",
    "batch_semantic_similarity",
    "match_terms",
    "normalize",
    "sbert_enabled",
    "sbert_info",
    "sbert_ready",
    "sbert_model_path",
    "semantic_similarity",
    "warmup_sbert",
    "spacy_available",
    "spacy_error",
    "spelling_available",
    "status",
    "warmup",
]
