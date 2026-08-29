"""ESSCAN rubric registry and loader.

Why this module exists
----------------------
Up to V7.9 there were effectively two unrelated rubrics:

* the professor configured "Semantic Relevance / Concept Coverage /
  Requirement Fulfillment / Keyword-Terminology / Grammar-Clarity" in
  CreateExam.jsx, which was saved into ``exam_rubrics``; and
* ``essay_grader.py`` graded with its own hard-coded weights read from
  ``ESSAY_WEIGHT_*`` environment variables over a different set of criteria
  (spelling / grammar / similarity / concept / keyword / structure).

So the rubric a professor configured was displayed but never used. This
module makes the stored rubric the single source of truth and gives every
criterion one canonical identity shared by the database, the grading engine
and both UIs.

Resolution order (per essay question):

    1. question-specific rubric   exam_rubrics.question_id = <question>
    2. legacy exam-level rubric   exam_rubrics.question_id IS NULL
    3. system default             DEFAULT_RUBRIC below

Nothing here writes to the database, and no schema change is required: the
existing ``exam_rubrics`` table already stores what is needed. Legacy
criterion names are recognised through aliases rather than being migrated.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger("esscan.rubric")


class Criterion:
    """One canonical grading criterion.

    ``technical_name`` is what goes in ``exam_rubrics.criterion_name`` — it is
    unchanged from V7.9 so existing rows keep working. ``label`` is the
    professor-facing wording.
    """

    __slots__ = ("key", "technical_name", "label", "description", "implementation",
                 "evidence_field", "evidence_label", "aliases", "in_default")

    def __init__(self, key, technical_name, label, description, implementation,
                 evidence_field, evidence_label, aliases, in_default=True):
        self.key = key
        self.technical_name = technical_name
        self.label = label
        self.description = description
        self.implementation = implementation
        # Which ExamQuestion field must be filled in for this criterion to be
        # measurable at all. None means it can always be evaluated.
        self.evidence_field = evidence_field
        self.evidence_label = evidence_label
        self.aliases = aliases
        self.in_default = in_default

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.technical_name,
            "label": self.label,
            "description": self.description,
            "implementation": self.implementation,
            "evidenceField": self.evidence_field,
            "evidenceLabel": self.evidence_label,
        }


CRITERIA: dict[str, Criterion] = {
    "semantic_relevance": Criterion(
        key="semantic_relevance",
        technical_name="Semantic Relevance",
        label="Answer Relevance",
        description="How closely the student's answer matches the meaning of the expected answer.",
        implementation="Sentence-BERT semantic comparison against the answer key",
        evidence_field="answer_key",
        evidence_label="answer key",
        aliases={"semantic relevance", "answer relevance", "similarity", "relevance",
                 "semantic similarity"},
    ),
    "concept_coverage": Criterion(
        key="concept_coverage",
        technical_name="Concept Coverage",
        label="Key Ideas",
        description="Whether the important ideas expected in the answer are present.",
        implementation="spaCy lemma-aware concept matching, supported by keyword evidence",
        evidence_field="key_concepts",
        evidence_label="key concepts",
        aliases={"concept coverage", "key ideas", "key concepts", "concept", "concepts"},
    ),
    "requirement_fulfillment": Criterion(
        key="requirement_fulfillment",
        technical_name="Requirement Fulfillment",
        label="Answer Completeness",
        description="Whether every required part of the question has been answered.",
        implementation="Requirement matching against the question's requirement list",
        evidence_field="requirements",
        evidence_label="requirements",
        aliases={"requirement fulfillment", "answer completeness", "completeness",
                 "requirements", "requirement"},
    ),
    "writing_quality": Criterion(
        key="writing_quality",
        technical_name="Grammar/Clarity",
        label="Writing Quality",
        description="Clarity and basic grammatical quality of the response.",
        implementation="spaCy linguistic analysis (grammar-weighted, spelling has limited influence)",
        evidence_field=None,
        evidence_label=None,
        # "spelling" folds in here: it is no longer a standalone criterion
        # because OCR of handwriting cannot reliably distinguish a student's
        # spelling mistake from a recognition error.
        aliases={"grammar/clarity", "grammar", "clarity", "writing quality",
                 "grammar and clarity", "spelling", "grammar & clarity"},
    ),
    "structure": Criterion(
        key="structure",
        technical_name="Structure",
        label="Organization and Structure",
        description="Whether the response matches the expected response format.",
        implementation="Response-format fit analysis",
        evidence_field=None,
        evidence_label=None,
        aliases={"structure", "organization", "organisation", "organization and structure",
                 "organisation and structure", "format"},
    ),
    # Retained so legacy exams that configured it keep grading exactly as the
    # professor set them up, but deliberately NOT part of the default rubric:
    # keywords are supporting evidence for Key Ideas, not a separate slice of
    # the final score.
    "keyword_terminology": Criterion(
        key="keyword_terminology",
        technical_name="Keyword/Terminology",
        label="Important Terms",
        description="Whether relevant subject-specific terms are used.",
        implementation="Keyword and terminology coverage",
        evidence_field="keywords",
        evidence_label="keywords",
        aliases={"keyword/terminology", "keyword match", "keywords", "keyword",
                 "important terms", "terminology"},
        in_default=False,
    ),
}

_ALIAS_INDEX: dict[str, str] = {}
for _crit in CRITERIA.values():
    _ALIAS_INDEX[_crit.key] = _crit.key
    _ALIAS_INDEX[_crit.technical_name.strip().lower()] = _crit.key
    _ALIAS_INDEX[_crit.label.strip().lower()] = _crit.key
    for _alias in _crit.aliases:
        _ALIAS_INDEX[_alias.strip().lower()] = _crit.key


# The professor-facing default. Keyword/Terminology is intentionally absent.
DEFAULT_RUBRIC: list[tuple[str, float]] = [
    ("semantic_relevance", 35.0),
    ("concept_coverage", 30.0),
    ("requirement_fulfillment", 20.0),
    ("writing_quality", 10.0),
    ("structure", 5.0),
]


def resolve_key(name: str) -> str | None:
    """Map any stored/legacy criterion name onto a canonical key."""
    if not name:
        return None
    return _ALIAS_INDEX.get(str(name).strip().lower())


def default_rubric_payload() -> list[dict[str, Any]]:
    """The default rubric in the shape the API and frontend exchange."""
    return [
        {"name": CRITERIA[key].technical_name, "weight": weight}
        for key, weight in DEFAULT_RUBRIC
    ]


class ResolvedRubric:
    """A rubric ready for grading: canonical keys with normalised weights."""

    __slots__ = ("entries", "source", "unknown_names")

    def __init__(self, entries: list[dict[str, Any]], source: str, unknown_names: list[str]):
        # entries: [{key, name, label, configuredWeight (0-100), weight (0-1)}]
        self.entries = entries
        # "question" | "exam_legacy" | "system_default"
        self.source = source
        self.unknown_names = unknown_names

    @property
    def keys(self) -> list[str]:
        return [e["key"] for e in self.entries]

    def weight_of(self, key: str) -> float:
        for entry in self.entries:
            if entry["key"] == key:
                return entry["weight"]
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "criteria": [dict(e) for e in self.entries],
            "unknownCriteria": list(self.unknown_names),
        }


def build_rubric(raw: Iterable[Any], source: str) -> ResolvedRubric:
    """Normalise raw (name, weight) pairs into a ResolvedRubric.

    ``raw`` items may be ORM ExamRubric rows, dicts, or (name, weight) tuples.
    Duplicate criteria (e.g. a legacy rubric with both "Spelling" and
    "Grammar", which both fold into Writing Quality) have their weights summed
    rather than one silently overwriting the other.
    """
    merged: dict[str, float] = {}
    order: list[str] = []
    unknown: list[str] = []

    for item in raw:
        if isinstance(item, dict):
            name, weight = item.get("name"), item.get("weight")
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            name, weight = item
        else:
            name = getattr(item, "criterion_name", None) or getattr(item, "name", None)
            weight = getattr(item, "weight", 0)

        key = resolve_key(name) or (name if name in CRITERIA else None)
        if key is None:
            if name:
                unknown.append(str(name))
            continue

        try:
            value = float(weight or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0:
            continue

        if key not in merged:
            merged[key] = 0.0
            order.append(key)
        merged[key] += value

    if not merged:
        # Nothing usable — fall back to the documented system default rather
        # than grading with an empty rubric.
        merged = {key: weight for key, weight in DEFAULT_RUBRIC}
        order = [key for key, _ in DEFAULT_RUBRIC]
        source = "system_default"

    total = sum(merged.values()) or 1.0
    entries = []
    for key in order:
        crit = CRITERIA[key]
        entries.append({
            "key": key,
            "name": crit.technical_name,
            "label": crit.label,
            "description": crit.description,
            "implementation": crit.implementation,
            "configuredWeight": round(merged[key], 2),
            # Normalised share used by the grading maths. Configured weights
            # are validated to total 100 at creation time, so this is normally
            # just configuredWeight/100.
            "weight": merged[key] / total,
        })
    return ResolvedRubric(entries, source, unknown)


def load_rubric_for_question(db, question) -> ResolvedRubric:
    """Load the rubric that actually governs this essay question.

    Order: question-specific rubric, then legacy exam-level rubric, then the
    system default. Callers pass the result into ``essay_grader.grade_answer``
    so the professor's configuration is what produces the score.
    """
    from models.exam_rubric import ExamRubric

    rows = (
        db.query(ExamRubric)
        .filter(ExamRubric.question_id == question.question_id)
        .order_by(ExamRubric.criterion_order)
        .all()
    )
    if rows:
        return build_rubric(rows, "question")

    legacy = (
        db.query(ExamRubric)
        .filter(ExamRubric.exam_id == question.exam_id, ExamRubric.question_id.is_(None))
        .order_by(ExamRubric.criterion_order)
        .all()
    )
    if legacy:
        return build_rubric(legacy, "exam_legacy")

    return build_rubric(DEFAULT_RUBRIC, "system_default")


def missing_evidence(criterion_key: str, question) -> str | None:
    """Return the human-readable name of the input this criterion needs but lacks.

    Used both by exam creation validation (to stop a professor configuring a
    criterion that can never be scored) and by the grader (to mark a criterion
    unavailable instead of silently dropping it).
    """
    crit = CRITERIA.get(criterion_key)
    if crit is None or crit.evidence_field is None:
        return None

    value = getattr(question, crit.evidence_field, None)
    if crit.evidence_field == "answer_key":
        return None if str(value or "").strip() else crit.evidence_label

    # key_concepts / keywords / requirements are stored as JSON text.
    from services.essay_grader import parse_json_list

    return None if parse_json_list(value) else crit.evidence_label


__all__ = [
    "CRITERIA",
    "Criterion",
    "DEFAULT_RUBRIC",
    "ResolvedRubric",
    "build_rubric",
    "default_rubric_payload",
    "load_rubric_for_question",
    "missing_evidence",
    "resolve_key",
]
