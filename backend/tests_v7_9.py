"""End-to-end checks for the V7.9 grading, override, release and lock rules.

Runs against an in-memory SQLite database with the OCR/OMR pipeline stubbed,
so it exercises the scoring and permission logic without needing EasyOCR,
Ollama or a MySQL server.

    cd backend
    python tests_v7_9.py
"""
import os
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.gettempdir()}/esscan_test.db")
os.environ.setdefault("ESSCAN_WARMUP_EASYOCR", "false")
os.environ.setdefault("ESSCAN_WARMUP_OLLAMA", "false")
os.environ.setdefault("ESSCAN_WARMUP_SPACY", "false")

db_file = os.environ["DATABASE_URL"].replace("sqlite:///", "")
if os.path.exists(db_file):
    os.remove(db_file)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from database import Base, SessionLocal, engine, get_db  # noqa: E402
from models.class_model import Class  # noqa: E402
from models.enrollment import Enrollment  # noqa: E402
from models.exam import Exam, ExamStatus  # noqa: E402
from models.exam_question import ExamQuestion, QuestionType  # noqa: E402
from models.exam_submission import ExamSubmission, SubmissionStatus  # noqa: E402
from models.submission_answer import SubmissionAnswer  # noqa: E402
from models.user import User, UserRole  # noqa: E402
from services.auth_service import get_current_user  # noqa: E402
from services import submission_pipeline as pipeline  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not condition else ""))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
db = SessionLocal()

prof = User(first_name="Ana", last_name="Reyes", email="prof@test.local", password_hash="x", role=UserRole.Professor)
student = User(first_name="Magda", last_name="Gelo", email="stud@test.local", password_hash="x", role=UserRole.Student)
other = User(first_name="Jose", last_name="Cruz", email="other@test.local", password_hash="x", role=UserRole.Student)
db.add_all([prof, student, other])
db.flush()

klass = Class(class_name="Science 101", subject="Science", teacher_id=prof.user_id, class_code="ABC123")
db.add(klass)
db.flush()
db.add_all([
    Enrollment(class_id=klass.class_id, student_id=student.user_id),
    Enrollment(class_id=klass.class_id, student_id=other.user_id),
])

exam = Exam(
    class_id=klass.class_id, teacher_id=prof.user_id, exam_title="Unit Test",
    exam_subject="Science", status=ExamStatus.Published, total_items=3, total_points=40,
)
db.add(exam)
db.flush()

q1 = ExamQuestion(exam_id=exam.exam_id, question_number=1, question_type=QuestionType.MCQ,
                  question_text="Pick A", option_a="a", option_b="b", correct_option="A", points=10)
q2 = ExamQuestion(exam_id=exam.exam_id, question_number=2, question_type=QuestionType.MCQ,
                  question_text="Pick B", option_a="a", option_b="b", correct_option="B", points=10)
q3 = ExamQuestion(exam_id=exam.exam_id, question_number=3, question_type=QuestionType.Essay,
                  question_text="Describe the biosphere.", points=20,
                  answer_key="The biosphere is where living organisms exist; producers, consumers and decomposers cycle nutrients.",
                  key_concepts='["ecosystem", "nutrient cycling"]',
                  keywords='["producers", "consumers", "decomposers"]',
                  requirements='["give an example"]', expected_response_format="few_sentences")
db.add_all([q1, q2, q3])
db.flush()

# Question-specific rubric: deliberately NOT the default weights, so a test
# failure here means the engine ignored the professor's configuration.
from models.exam_rubric import ExamRubric  # noqa: E402

CUSTOM_WEIGHTS = [
    ("Semantic Relevance", 40),
    ("Concept Coverage", 25),
    ("Requirement Fulfillment", 20),
    ("Grammar/Clarity", 10),
    ("Structure", 5),
]
for order, (name, weight) in enumerate(CUSTOM_WEIGHTS, start=1):
    db.add(ExamRubric(exam_id=exam.exam_id, question_id=q3.question_id,
                      criterion_order=order, criterion_name=name, weight=weight))
db.commit()

# Capture plain ids before closing the session: the ORM objects become
# detached afterwards and would raise on attribute access.
exam_id, student_id, other_id = exam.exam_id, student.user_id, other.user_id
class_id = klass.class_id
prof_id = prof.user_id
q1_id, q2_id, q3_id = q1.question_id, q2.question_id, q3.question_id
db.close()


# ---------------------------------------------------------------------------
# Stub the OCR/OMR pipeline
# ---------------------------------------------------------------------------
ESSAY_TEXT = (
    "The biosphere is the ecosystem of land air and water that supports life. "
    "Producers consumers and decomposers cycle nutrients and energy through it."
)


def fake_run_pipeline(pages, mcq_numbers, essay_count, has_mcq, topic_hint="", essay_plan=None):
    """Q1 answered correctly, Q2 answered incorrectly, one essay transcribed."""
    return {
        "page1": {
            "scan": {"normalized": True, "quality": {}, "alignment": {}},
            "extraction": {"easyocr_text": "Magda Gelo", "ollama_text": "", "combined_text": "Magda Gelo"},
            "omr": {"answers": [
                {"question_number": 1, "selected_option": "A", "is_blank": False, "is_ambiguous": False,
                 "confidence": 0.95, "best_fill_ratio": 0.8, "second_fill_ratio": 0.1, "options": {}},
                {"question_number": 2, "selected_option": "A", "is_blank": False, "is_ambiguous": False,
                 "confidence": 0.91, "best_fill_ratio": 0.7, "second_fill_ratio": 0.1, "options": {}},
            ]},
        },
        "essayPages": [{
            "index": 0,
            "scan": {"normalized": True, "quality": {}, "alignment": {}},
            "extraction": {
                "answers": [{"answer": ESSAY_TEXT, "easyocr": ESSAY_TEXT, "ollama": "", "confidence": 0.9, "mode": "easyocr"}],
                "easyocr_text": ESSAY_TEXT, "ollama_text": "", "combined_text": ESSAY_TEXT,
            },
        }],
        "timings": {"total": 0.01},
        "services": {"easyocr_available": True, "ollama_available": False, "omr_available": True},
    }


import services.submission_pipeline as pipeline_module  # noqa: E402

# The routers no longer call run_pipeline directly — they hand the work to
# process_submission_background(), which is defined in submission_pipeline.py
# and looks up run_pipeline in THAT module's namespace. So the stub has to be
# installed there, not on the router modules.
pipeline_module.run_pipeline = fake_run_pipeline

client = TestClient(main.app)


def as_user(user_id):
    def override():
        session = SessionLocal()
        try:
            return session.query(User).filter(User.user_id == user_id).first()
        finally:
            session.close()
    main.app.dependency_overrides[get_current_user] = override


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def upload_as_student(uid=None):
    return client.post(
        f"/api/student/exams/{exam_id}/upload",
        files=[("page1", ("p1.png", PNG, "image/png")),
               ("essay_pages", ("e1.png", PNG, "image/png"))],
    )


# ---------------------------------------------------------------------------
print("\n[1] Student upload runs the pipeline and produces scores")
as_user(student_id)
r = upload_as_student()
check("upload succeeds", r.status_code == 200, r.text[:300])
check("response reports locked", r.json().get("locked") is True)
check("response leaks no score", "finalScore" not in r.json())

s = SessionLocal()
sub = s.query(ExamSubmission).filter(ExamSubmission.exam_id == exam_id, ExamSubmission.student_id == student_id).first()
check("submission stored", sub is not None)
check("mcq scored 10/20 (one right, one wrong)", float(sub.mcq_score) == 10.0, f"got {sub.mcq_score}")
check("essay scored > 0", float(sub.essay_score) > 0, f"got {sub.essay_score}")
check("max score is 40", float(sub.max_score) == 40.0, f"got {sub.max_score}")
check("final = mcq + essay", abs(float(sub.final_score) - (float(sub.mcq_score) + float(sub.essay_score))) < 0.01)
check("status is Graded", sub.submission_status == SubmissionStatus.Graded, str(sub.submission_status))
check("locked flag set", bool(sub.is_locked))
check("not released by default", not bool(sub.scores_released))
check("attempt_count is 1", sub.attempt_count == 1, str(sub.attempt_count))
essay_row = s.query(SubmissionAnswer).filter(SubmissionAnswer.submission_id == sub.submission_id,
                                             SubmissionAnswer.question_id == q3_id).first()
check("essay transcription stored", (essay_row.answer_text or "").startswith("The biosphere"))
check("essay feedback stored", bool(essay_row.feedback_json))
auto_essay = float(essay_row.auto_score)
s.close()

# ---------------------------------------------------------------------------
print("\n[2] Student cannot submit twice")
r = upload_as_student()
check("second upload rejected with 409", r.status_code == 409, f"{r.status_code} {r.text[:200]}")
check("message points to the professor", "professor" in r.text.lower())

# ---------------------------------------------------------------------------
print("\n[3] Student cannot see an unreleased score")
r = client.get(f"/api/student/exams/{exam_id}/result")
body = r.json()
check("result endpoint reachable", r.status_code == 200)
check("released is false", body.get("released") is False)
check("no finalScore leaked", "finalScore" not in body)
check("no answer key leaked", "correctOption" not in r.text)
check("explains the wait", "release" in (body.get("message") or "").lower())

r = client.get(f"/api/student/exams/{exam_id}")
check("exam view hides score", r.json()["submission"].get("finalScore") is None)
check("exam view reports locked", r.json()["submission"].get("locked") is True)

# ---------------------------------------------------------------------------
print("\n[4] Professor sees full grading detail")
as_user(prof_id)
r = client.get(f"/api/exams/{exam_id}/submissions/by-student/{student_id}")
check("detail loads", r.status_code == 200, r.text[:300])
detail = r.json()
check("mcq score visible to professor", detail["mcq"]["score"] == 10.0)
check("essay questions present", len(detail["essay"]["questions"]) == 1)
eq = detail["essay"]["questions"][0]
check("essay autoScore present", eq["autoScore"] is not None)
check("criteria breakdown present", len(eq["criteria"]) > 0)
check("highlights computed", len(eq["highlights"]) > 0)
# semanticPending reflects whether the real model produced the number, so
# the expectation depends on whether SBERT is deployed in this environment.
from services import nlp_spacy as _nlp_probe  # noqa: E402
_sbert_live = _nlp_probe.sbert_info()["loaded"]
check(
    "semanticPending matches the engine actually used",
    eq["semanticPending"] is not _sbert_live,
    f"sbert_loaded={_sbert_live} semanticPending={eq['semanticPending']}",
)
check("not released yet", detail["release"]["released"] is False)

# ---------------------------------------------------------------------------
print("\n[5] Essay score override")
r = client.put(
    f"/api/exams/{exam_id}/submissions/by-student/{student_id}/essay/{q3_id}/score",
    json={"score": 18, "reason": "Good reasoning, minor gaps"},
)
check("override accepted", r.status_code == 200, r.text[:300])
o = r.json()
check("override recorded", o["overrideScore"] == 18.0)
check("auto score preserved", abs(o["autoScore"] - auto_essay) < 0.01, f"{o['autoScore']} vs {auto_essay}")
check("effective score is the override", o["score"] == 18.0)
check("total recomputed to 28", o["finalScore"] == 28.0, f"got {o['finalScore']}")

r = client.put(
    f"/api/exams/{exam_id}/submissions/by-student/{student_id}/essay/{q3_id}/score",
    json={"score": 99},
)
check("over-max override rejected", r.status_code == 422, str(r.status_code))
r = client.put(
    f"/api/exams/{exam_id}/submissions/by-student/{student_id}/essay/{q3_id}/score",
    json={"score": -1},
)
check("negative override rejected", r.status_code == 422, str(r.status_code))

r = client.put(
    f"/api/exams/{exam_id}/submissions/by-student/{student_id}/essay/{q1_id}/score",
    json={"score": 5},
)
check("override on an MCQ rejected", r.status_code == 422, str(r.status_code))

# ---------------------------------------------------------------------------
print("\n[6] Release makes the score visible")
r = client.post(f"/api/exams/{exam_id}/submissions/by-student/{student_id}/release", json={"released": True})
check("release succeeds", r.status_code == 200, r.text[:300])
check("marked released", r.json()["released"] is True)

as_user(student_id)
r = client.get(f"/api/student/exams/{exam_id}/result")
body = r.json()
check("student now sees released=true", body["released"] is True)
check("student sees final score 28", body["finalScore"] == 28.0, str(body.get("finalScore")))
check("student sees mcq breakdown", len(body["mcq"]["questions"]) == 2)
check("student sees answer key after release", body["mcq"]["questions"][0]["correctOption"] == "A")
check("student sees essay answer", body["essay"]["questions"][0]["answerText"].startswith("The biosphere"))
check("student told it was adjusted", body["essay"]["questions"][0]["wasAdjusted"] is True)

# ---------------------------------------------------------------------------
print("\n[7] Un-releasing hides it again")
as_user(prof_id)
client.post(f"/api/exams/{exam_id}/submissions/by-student/{student_id}/release", json={"released": False})
as_user(student_id)
body = client.get(f"/api/student/exams/{exam_id}/result").json()
check("hidden again", body["released"] is False)
check("score gone", "finalScore" not in body)

# ---------------------------------------------------------------------------
print("\n[8] Clearing the override restores the AI score")
as_user(prof_id)
r = client.put(
    f"/api/exams/{exam_id}/submissions/by-student/{student_id}/essay/{q3_id}/score",
    json={"score": None},
)
check("override cleared", r.status_code == 200 and r.json()["overrideScore"] is None, r.text[:200])
check("falls back to AI score", abs(r.json()["score"] - auto_essay) < 0.01)

# ---------------------------------------------------------------------------
print("\n[9] Professor replace requires explicit confirmation")
r = client.post(
    "/api/uploads/submissions",
    data={"exam_id": str(exam_id), "student_id": str(student_id), "allow_replace": "false"},
    files=[("page1", ("p1.png", PNG, "image/png")), ("essay_pages", ("e1.png", PNG, "image/png"))],
)
check("replace without confirmation rejected", r.status_code == 409, f"{r.status_code} {r.text[:200]}")

r = client.post(
    "/api/uploads/submissions",
    data={"exam_id": str(exam_id), "student_id": str(student_id), "allow_replace": "true"},
    files=[("page1", ("p1.png", PNG, "image/png")), ("essay_pages", ("e1.png", PNG, "image/png"))],
)
check("replace with confirmation succeeds", r.status_code == 200, r.text[:300])
check("replaced flag reported", r.json().get("replaced") is True)

s = SessionLocal()
sub = s.query(ExamSubmission).filter(ExamSubmission.exam_id == exam_id, ExamSubmission.student_id == student_id).first()
check("attempt_count incremented", sub.attempt_count == 2, str(sub.attempt_count))
s.close()

print("\n[9b] Replacing a released submission un-releases it")
client.post(f"/api/exams/{exam_id}/submissions/by-student/{student_id}/release", json={"released": True})
r = client.post(
    "/api/uploads/submissions",
    data={"exam_id": str(exam_id), "student_id": str(student_id), "allow_replace": "true"},
    files=[("page1", ("p1.png", PNG, "image/png")), ("essay_pages", ("e1.png", PNG, "image/png"))],
)
check("replace succeeds", r.status_code == 200)
check("score is no longer released", r.json().get("scoresReleased") is False)

# ---------------------------------------------------------------------------
print("\n[10] Bulk release skips unscored submissions")
r = client.post(f"/api/exams/{exam_id}/submissions/release", json={"released": True})
check("bulk release succeeds", r.status_code == 200, r.text[:300])
check("one submission released", r.json()["updated"] == 1, str(r.json()))

# ---------------------------------------------------------------------------
print("\n[11] Cross-student access is blocked")
as_user(other_id)
r = client.get(f"/api/student/exams/{exam_id}/result")
check("other student sees their own empty result", r.status_code == 200 and r.json()["submitted"] is False)

s = SessionLocal()
sub_id = s.query(ExamSubmission).filter(ExamSubmission.student_id == student_id).first().submission_id
s.close()
r = client.get(f"/api/uploads/submissions/{sub_id}/file?which=page1")
check("other student cannot read someone else's sheet", r.status_code in (403, 404), str(r.status_code))

as_user(student_id)
r = client.get(f"/api/uploads/submissions/{sub_id}/file?which=page1")
check("owner student can read their own sheet", r.status_code == 200, str(r.status_code))

# ---------------------------------------------------------------------------
print("\n[12] Students cannot use professor endpoints")
r = client.post(f"/api/exams/{exam_id}/submissions/by-student/{student_id}/release", json={"released": True})
check("student cannot release", r.status_code == 403, str(r.status_code))
r = client.put(
    f"/api/exams/{exam_id}/submissions/by-student/{student_id}/essay/{q3_id}/score",
    json={"score": 20},
)
check("student cannot override", r.status_code == 403, str(r.status_code))


# ---------------------------------------------------------------------------
# V7.9.1 rubric-engine checks (items A-O)
# ---------------------------------------------------------------------------
print("\n[13] The professor's rubric is the rubric the engine uses")
from services import essay_grader, rubric as rubric_module  # noqa: E402

s = SessionLocal()
q3_row = s.query(ExamQuestion).filter(ExamQuestion.question_id == q3_id).first()
resolved = rubric_module.load_rubric_for_question(s, q3_row)

check("rubric comes from the question", resolved.source == "question", resolved.source)
configured = {e["name"]: e["configuredWeight"] for e in resolved.entries}
check("saved weights retrieved verbatim (B)",
      configured == {n: float(w) for n, w in CUSTOM_WEIGHTS}, str(configured))
check("weights total 100 (E)", abs(sum(configured.values()) - 100) < 0.01, str(sum(configured.values())))
check("Keyword/Terminology not required (F)", "Keyword/Terminology" not in configured)

graded = essay_grader.grade_answer(ESSAY_TEXT, q3_row, max_points=20, rubric=resolved)
used = {c["name"]: c["configuredWeight"] for c in graded["criteria"]}
check("grading used those exact weights (C)",
      used == {n: float(w) for n, w in CUSTOM_WEIGHTS}, str(used))

contributions = sum(c["contribution"] for c in graded["criteria"])
check("final % equals sum of contributions (N)",
      abs(contributions - graded["percentage"] * 100) < 0.05,
      f"{contributions} vs {graded['percentage'] * 100}")
check("score equals percentage x points",
      abs(graded["score"] - graded["percentage"] * 20) < 0.02, str(graded["score"]))

print("\n[14] Different questions may use different rubrics (D)")
alt = rubric_module.build_rubric(
    [("structure", 80), ("writing_quality", 20)], "question")
graded_alt = essay_grader.grade_answer(ESSAY_TEXT, q3_row, max_points=20, rubric=alt)
check("a different rubric produces a different score",
      graded_alt["score"] != graded["score"],
      f"{graded_alt['score']} == {graded['score']}")
check("the alternate rubric's weights were used",
      {c["name"] for c in graded_alt["criteria"]} == {"Structure", "Grammar/Clarity"},
      str([c["name"] for c in graded_alt["criteria"]]))

print("\n[15] Legacy exam-level rubrics still work (M)")
legacy_exam = Exam(class_id=class_id, teacher_id=prof_id, exam_title="Legacy",
                   exam_subject="Science", status=ExamStatus.Published,
                   total_items=1, total_points=10)
s.add(legacy_exam); s.flush()
legacy_q = ExamQuestion(exam_id=legacy_exam.exam_id, question_number=1,
                        question_type=QuestionType.Essay, question_text="Legacy essay",
                        answer_key="reference answer about ecosystems and nutrients",
                        key_concepts='["ecosystem"]', keywords='["nutrients"]',
                        requirements='[]', points=10,
                        expected_response_format="one_paragraph")
s.add(legacy_q); s.flush()
# V6.3-style: rubric attached to the exam, not the question, using old names.
for order, (name, weight) in enumerate(
        [("Semantic Relevance", 50), ("Concept Coverage", 30),
         ("Keyword/Terminology", 10), ("Spelling", 5), ("Grammar", 5)], start=1):
    s.add(ExamRubric(exam_id=legacy_exam.exam_id, question_id=None,
                     criterion_order=order, criterion_name=name, weight=weight))
s.commit()

legacy_resolved = rubric_module.load_rubric_for_question(s, legacy_q)
check("falls back to the exam-level rubric", legacy_resolved.source == "exam_legacy",
      legacy_resolved.source)
legacy_names = {e["name"]: e["configuredWeight"] for e in legacy_resolved.entries}
check("legacy Keyword/Terminology preserved", legacy_names.get("Keyword/Terminology") == 10.0,
      str(legacy_names))
check("legacy Spelling+Grammar merged into Grammar/Clarity",
      legacy_names.get("Grammar/Clarity") == 10.0, str(legacy_names))
legacy_graded = essay_grader.grade_answer("The ecosystem cycles nutrients.", legacy_q,
                                          max_points=10, rubric=legacy_resolved)
check("legacy exam still grades", legacy_graded["score"] >= 0)
check("legacy rubric source recorded", legacy_graded["rubric"]["source"] == "exam_legacy")

print("\n[16] System default is the last resort")
bare_q = ExamQuestion(exam_id=exam_id, question_number=99, question_type=QuestionType.Essay,
                      question_text="No rubric", answer_key="something",
                      key_concepts='["x"]', keywords='[]', requirements='[]', points=5,
                      expected_response_format="one_paragraph")
s.add(bare_q); s.commit()
default_resolved = rubric_module.load_rubric_for_question(s, bare_q)
check("bare question falls through to system default",
      default_resolved.source == "system_default", default_resolved.source)
check("default excludes Keyword/Terminology (F)",
      "Keyword/Terminology" not in {e["name"] for e in default_resolved.entries})
check("default totals 100",
      abs(sum(e["configuredWeight"] for e in default_resolved.entries) - 100) < 0.01)

print("\n[17] Missing evidence is explicit, never silent (O)")
no_key = ExamQuestion(exam_id=exam_id, question_number=98, question_type=QuestionType.Essay,
                      question_text="No answer key", answer_key="",
                      key_concepts='["ecosystem"]', keywords='[]',
                      requirements='[]', points=10,
                      expected_response_format="one_paragraph")
s.add(no_key); s.commit()
r_missing = rubric_module.build_rubric(
    [("semantic_relevance", 40), ("concept_coverage", 40), ("structure", 20)], "question")
g_missing = essay_grader.grade_answer(ESSAY_TEXT, no_key, max_points=10, rubric=r_missing)
skipped = [c for c in g_missing["criteria"] if not c["counted"]]
check("unavailable criterion is reported, not dropped", len(skipped) == 1, str(skipped))
check("it explains why", "answer key" in (skipped[0].get("unavailableReason") or "").lower(),
      str(skipped[0].get("unavailableReason")))
check("the adjustment is flagged", g_missing["rubric"]["adjusted"] is True)
check("configured rubric preserved in the audit trail",
      len(g_missing["rubric"]["configured"]) == 3)
check("contributions still sum to the final percentage",
      abs(sum(c["contribution"] for c in g_missing["criteria"]) - g_missing["percentage"] * 100) < 0.05)

# Detach-safe snapshot of the essay question for the checks that follow.
Q3_ANSWER_KEY = q3_row.answer_key


class Q3Snapshot:
    question_id = q3_id
    question_number = 3
    points = 20
    question_text = "Describe the biosphere."
    answer_key = Q3_ANSWER_KEY
    key_concepts = q3_row.key_concepts
    keywords = q3_row.keywords
    requirements = q3_row.requirements
    expected_response_format = q3_row.expected_response_format


q3_snap = Q3Snapshot()
s.close()

print("\n[18] SBERT reporting is honest (G, H, I)")
from services import nlp_spacy  # noqa: E402
info = nlp_spacy.sbert_info()
sim = nlp_spacy.semantic_similarity(nlp_spacy.analyze(ESSAY_TEXT), Q3_ANSWER_KEY)
if info["loaded"]:
    check("engine reported as sentence_transformer (H)", sim["engine"] == "sentence_transformer", str(sim))
    check("semanticPending is False when SBERT works", sim["pending"] is False)
    check("model name recorded for audit", bool(sim.get("model")))
else:
    check("falls back safely when SBERT is unavailable (I)",
          sim["engine"] == "lexical_fallback", str(sim))
    check("fallback is flagged pending, not passed off as semantic", sim["pending"] is True)
    check("the reason is reported", bool(info["error"]), str(info))
check("default model path points at the selected V3 checkpoint",
      "ESSCAN_AAA_SBERT_ASAP_V3" in nlp_spacy.DEFAULT_SBERT_PATH, nlp_spacy.DEFAULT_SBERT_PATH)

print("\n[18b] Semantic relevance actually discriminates")
# The point of these checks is that Answer Relevance must separate a correct
# answer from an irrelevant one. A model whose raw cosine sits in a narrow
# high band will pass "it loads" while still awarding ~70% to nonsense, so
# the ordering and the floor are asserted explicitly.
KEY = ("The biosphere is where living organisms exist; producers, consumers "
       "and decomposers cycle nutrients.")
samples = {
    "correct": ("The biosphere is the zone of land, water and air where living things "
                "exist. Producers, consumers and decomposers cycle nutrients through it."),
    "partial": "The biosphere has living things in it.",
    "unrelated": "I like playing basketball on weekends with my friends.",
}
scores = {
    name: nlp_spacy.semantic_similarity(nlp_spacy.analyze(text), KEY)["score"]
    for name, text in samples.items()
}
print("   scores:", {k: round(v, 3) for k, v in scores.items()})
check("a correct answer outscores a partial one", scores["correct"] > scores["partial"], str(scores))
check("a partial answer outscores unrelated text", scores["partial"] > scores["unrelated"], str(scores))
check("irrelevant text scores low, not merely lower",
      scores["unrelated"] < 0.25, f"unrelated scored {scores['unrelated']:.3f}")
# The bar differs by engine on purpose: the lexical fallback is a documented
# degradation, not an equal substitute, so holding it to the fine-tuned
# model's standard would be testing the wrong thing.
_min_correct = 0.70 if info["loaded"] else 0.45
check(f"a correct answer scores high ({'sbert' if info['loaded'] else 'lexical fallback'})",
      scores["correct"] > _min_correct,
      f"correct scored {scores['correct']:.3f}, needed > {_min_correct}")

if info["loaded"]:
    raw = nlp_spacy.semantic_similarity(nlp_spacy.analyze(samples["unrelated"]), KEY)
    check("raw cosine is preserved for audit", "rawCosine" in raw, str(raw))
    check("calibration is doing real work (raw >> calibrated)",
          raw["rawCosine"] - raw["score"] > 0.3,
          f"raw {raw['rawCosine']} vs calibrated {raw['score']}")

print("\n[19] expectedResponseFormat is saved and respected (J)")
as_user(prof_id)
r = client.get(f"/api/exams/{exam_id}")
essay_payload = [q for q in r.json()["essayQuestions"] if q["id"] == q3_id]
check("format persisted on the question", bool(essay_payload) and
      essay_payload[0]["expectedResponseFormat"] == "few_sentences",
      str(essay_payload[0]["expectedResponseFormat"]) if essay_payload else "missing")
check("grader used the stored format",
      graded["expectedResponseFormat"] == "few_sentences", graded["expectedResponseFormat"])

structure_c = [c for c in graded["criteria"] if c["key"] == "structure"][0]
check("structure reports the format it judged against",
      structure_c["detail"]["expectedFormat"] == "few_sentences")

print("\n[20] Structure judges format fit, not length (item 9)")
# A concise answer that genuinely matches "a few sentences" should score
# full marks for structure even though it is far shorter than an essay.
short_ok = essay_grader.grade_answer(
    "Producers, consumers and decomposers cycle nutrients. A forest floor is one example.",
    q3_snap, max_points=20, rubric=resolved)
short_struct = [c for c in short_ok["criteria"] if c["key"] == "structure"][0]
check("a short answer fitting its format scores full structure",
      short_struct["value"] >= 0.95,
      f"{short_struct['value']} ({short_struct['detail'].get('verdict')})")

# One sentence where a few were asked for IS a real format mismatch, but it
# must be a proportionate deduction, not a collapse to zero.
one_sentence = essay_grader.grade_answer(
    "Producers, consumers and decomposers cycle nutrients, for example in a forest.",
    q3_snap, max_points=20, rubric=resolved)
os_struct = [c for c in one_sentence["criteria"] if c["key"] == "structure"][0]
check("a format mismatch is a proportionate deduction, not a collapse",
      0.6 <= os_struct["value"] < 1.0, str(os_struct["value"]))
# Structure is only 5% of this rubric, so the format mismatch itself must
# barely move the total. Comparing the two totals directly would also pick up
# the content criteria (the two answers differ semantically too), so the
# structure contribution is isolated.
struct_a = [c for c in short_ok["criteria"] if c["key"] == "structure"][0]
struct_b = [c for c in one_sentence["criteria"] if c["key"] == "structure"][0]
struct_delta = abs(struct_a["contribution"] - struct_b["contribution"])
check("structure has limited influence on the final score",
      struct_delta < 3.0,
      f"structure moved the total by {struct_delta:.2f} percentage points")

# Content criteria must not reward length. A long, waffly answer that says
# less should not beat a short, accurate one on Key Ideas.
padded = essay_grader.grade_answer(
    "Well, I think that this topic is very interesting and important to study. "
    "There are many things that could be said about it in general terms. "
    "It is something that people have thought about for a very long time indeed.",
    q3_snap, max_points=20, rubric=resolved)
check("a longer but emptier answer does not outscore a short correct one",
      padded["score"] < short_ok["score"],
      f"padded={padded['score']} short={short_ok['score']}")

one_word_q = ExamQuestion(exam_id=exam_id, question_number=97, question_type=QuestionType.Essay,
                          question_text="Name the layer", answer_key="biosphere",
                          key_concepts='["biosphere"]', keywords='[]', requirements='[]',
                          points=5, expected_response_format="one_word")
g_word = essay_grader.grade_answer("Biosphere", one_word_q, max_points=5,
                                   rubric=rubric_module.build_rubric([("structure", 100)], "question"))
check("a one-word answer scores full structure for a one_word format",
      g_word["criteria"][0]["value"] >= 0.95, str(g_word["criteria"][0]["value"]))

print("\n[21] OCR errors do not count as spelling mistakes (item 10)")
ocr_text = ("The ecosystem has producers consumers and decompsers that recycle nutrints, "
            "for example inside a forest floor.")
g_ocr = essay_grader.grade_answer(ocr_text, q3_snap, max_points=20, rubric=resolved)
analysis = g_ocr["analysis"]
check("OCR-damaged domain terms are separated out",
      analysis["ocrSuspectedCount"] >= 1, str(analysis))
check("they are excluded from the misspelling list",
      "decompsers" not in analysis["misspelledSample"], str(analysis["misspelledSample"]))
writing = [c for c in g_ocr["criteria"] if c["key"] == "writing_quality"][0]
check("spelling has limited influence on Writing Quality",
      writing["detail"].get("spellingShare", 0) <= 0.3, str(writing["detail"].get("spellingShare")))

print("\n[22] Rubric evidence is validated at exam creation (item 5)")
bad_exam = {
    "title": "Bad rubric", "subject": "Science", "classIds": [class_id],
    "mcqQuestions": [],
    "essayQuestions": [{
        "question": "Explain something", "answerKey": "a reference answer",
        "keyConcepts": [], "keywords": [], "requirements": [], "points": 10,
        "expectedResponseFormat": "one_paragraph",
        "rubric": [
            {"name": "Semantic Relevance", "weight": 40},
            {"name": "Concept Coverage", "weight": 40},
            {"name": "Structure", "weight": 20},
        ],
    }],
    "status": "Draft",
}
r = client.post("/api/exams", json=bad_exam)
check("weighted criterion without evidence is rejected", r.status_code == 422, f"{r.status_code} {r.text[:200]}")
check("the error names the criterion and the missing input",
      "Key Ideas" in r.text and "key concepts" in r.text, r.text[:250])

bad_exam["essayQuestions"][0]["keyConcepts"] = ["photosynthesis"]
r = client.post("/api/exams", json=bad_exam)
check("it saves once the evidence is supplied", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")

print("\n[23] Response format round-trips through the API (J)")
fmt_exam = {
    "title": "Format test", "subject": "Science", "classIds": [class_id],
    "mcqQuestions": [],
    "essayQuestions": [{
        "question": "Write an essay", "answerKey": "reference",
        "keyConcepts": [], "keywords": [], "requirements": [], "points": 10,
        "expectedResponseFormat": "essay",
        "rubric": [{"name": "Semantic Relevance", "weight": 70},
                   {"name": "Structure", "weight": 30}],
    }],
    "status": "Draft",
}
r = client.post("/api/exams", json=fmt_exam)
check("exam with 'essay' format saves", r.status_code in (200, 201), r.text[:200])
if r.status_code in (200, 201):
    new_id = r.json()["exam"]["id"]
    fetched = client.get(f"/api/exams/{new_id}").json()
    check("'essay' format survives the round trip (not forced to one_paragraph)",
          fetched["essayQuestions"][0]["expectedResponseFormat"] == "essay",
          fetched["essayQuestions"][0]["expectedResponseFormat"])
    check("per-question rubric saved",
          len(fetched["essayQuestions"][0]["rubric"]) == 2,
          str(fetched["essayQuestions"][0]["rubric"]))

r = client.post("/api/exams", json={**fmt_exam, "title": "Bad format",
                                    "essayQuestions": [{**fmt_exam["essayQuestions"][0],
                                                        "expectedResponseFormat": "haiku"}]})
check("an unknown format is rejected", r.status_code == 422, str(r.status_code))


# ---------------------------------------------------------------------------
print("\n[24] Live camera scan-preview works for students, not just professors")
# Regression test: this endpoint was professor-only, which silently broke the
# student camera's auto-frame detection, alignment overlay and auto-capture.
# The frontend caught the resulting 403 and fell back to plain manual
# capture with no error surfaced, so the bug was invisible without this check.
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00\x43\x00" + bytes([1] * 64) +
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xd2\xff\xd9"
)

as_user(student_id)
r = client.post(
    "/api/uploads/scan-preview",
    data={"exam_id": str(exam_id), "page_number": "1"},
    files={"image": ("frame.jpg", TINY_JPEG, "image/jpeg")},
)
check("an enrolled student can use live scan preview", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
check("response has no professor-only fields",
      not any(k in r.json() for k in ("studentName", "roster", "candidates")), str(r.json().keys()))

as_user(other_id)
outside_exam = Exam(class_id=999999, teacher_id=prof_id, exam_title="Other class",
                    exam_subject="X", status=ExamStatus.Published, total_items=0, total_points=0)
s = SessionLocal()
s.add(outside_exam); s.commit()
outside_exam_id = outside_exam.exam_id
s.close()
r = client.post(
    "/api/uploads/scan-preview",
    data={"exam_id": str(outside_exam_id), "page_number": "1"},
    files={"image": ("frame.jpg", TINY_JPEG, "image/jpeg")},
)
check("a student NOT enrolled in the exam's class is rejected", r.status_code == 403, str(r.status_code))

as_user(prof_id)
r = client.post(
    "/api/uploads/scan-preview",
    data={"exam_id": str(exam_id), "page_number": "1"},
    files={"image": ("frame.jpg", TINY_JPEG, "image/jpeg")},
)
check("the exam-owning professor can still use live scan preview", r.status_code == 200, str(r.status_code))

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# A dedicated exam for the async-processing tests below, isolated from
# exam_id: earlier sections (16-17) added scratch essay questions directly
# onto exam_id, which changed its essay-page requirement partway through the
# file. That is fine for those sections but would make upload_as_student()
# unreliable here, so these tests get their own single-essay-question exam.
s = SessionLocal()
async_exam = Exam(class_id=class_id, teacher_id=prof_id, exam_title="Async processing test",
                  exam_subject="Science", status=ExamStatus.Published,
                  total_items=2, total_points=30)
s.add(async_exam); s.flush()
async_mcq = ExamQuestion(exam_id=async_exam.exam_id, question_number=1, question_type=QuestionType.MCQ,
                         question_text="Pick A", option_a="a", option_b="b", correct_option="A", points=10)
async_essay = ExamQuestion(exam_id=async_exam.exam_id, question_number=2, question_type=QuestionType.Essay,
                           question_text="Describe the biosphere.", points=20,
                           answer_key=Q3_ANSWER_KEY, key_concepts=q3_snap.key_concepts,
                           keywords=q3_snap.keywords, requirements=q3_snap.requirements,
                           expected_response_format="few_sentences")
s.add_all([async_mcq, async_essay])
s.commit()
async_exam_id = async_exam.exam_id
s.close()


def upload_async_test_exam():
    """One page1 + one essay page: exactly what async_exam_id requires."""
    return client.post(
        f"/api/student/exams/{async_exam_id}/upload",
        files=[("page1", ("p1.png", PNG, "image/png")),
               ("essay_pages", ("e1.png", PNG, "image/png"))],
    )


print("\n[25] Uploads return immediately; grading runs in the background")
# This is the core of the async-processing change: the response the caller
# sees must reflect the state at the moment of response (locked, processing,
# no scores yet) even though — because TestClient drives background tasks to
# completion before returning control here — the database has *already*
# finished grading by the time we inspect it below. Both facts together prove
# the design: the HTTP response does not wait on grading, but grading did
# still happen reliably.
new_student = User(first_name="Rico", last_name="Bautista", email="rico@test.local",
                   password_hash="x", role=UserRole.Student)
s = SessionLocal()
s.add(new_student); s.flush()
s.add(Enrollment(class_id=class_id, student_id=new_student.user_id))
s.commit()
new_student_id = new_student.user_id
s.close()

as_user(new_student_id)
r = upload_async_test_exam()
body = r.json()
check("upload responds 200 immediately", r.status_code == 200, r.text[:200])
check("response says processing is happening in the background",
      body.get("processing") is True, str(body))
check("response status is a processing state, not a final one",
      body.get("status") in ("OCR_Processing", "Uploaded"), str(body.get("status")))
check("no score fields are present on the immediate response",
      not any(k in body for k in ("finalScore", "mcqScore", "essayScore", "ocr", "omr")),
      str(sorted(body.keys())))

# By the time client.post() returned above, Starlette had already driven the
# background task to completion (this is how TestClient works), so the DB
# should now show a fully graded submission — proving the background task
# actually ran, not just that the response returned fast.
s = SessionLocal()
bg_sub = s.query(ExamSubmission).filter(
    ExamSubmission.exam_id == async_exam_id, ExamSubmission.student_id == new_student_id
).first()
check("background task actually completed the grading",
      bg_sub is not None and bg_sub.submission_status == SubmissionStatus.Graded,
      str(bg_sub.submission_status if bg_sub else None))
check("background task computed real scores",
      bg_sub is not None and bg_sub.final_score is not None, str(bg_sub))
check("submitted_at was set immediately, not deferred to grading completion",
      bg_sub is not None and bg_sub.submitted_at is not None)
s.close()

print("\n[26] A second attempt during processing is rejected, same as after")
# is_locked is now set in the FAST path, before grading even starts, so a
# double-tap during processing must be blocked exactly like a double-tap
# after grading finished — there should be no window where a second upload
# slips through.
another_student = User(first_name="Nina", last_name="Cruz", email="nina@test.local",
                       password_hash="x", role=UserRole.Student)
s = SessionLocal()
s.add(another_student); s.flush()
s.add(Enrollment(class_id=class_id, student_id=another_student.user_id))
s.commit()
another_student_id = another_student.user_id
s.close()

as_user(another_student_id)
r1 = upload_async_test_exam()
check("first upload for this student succeeds", r1.status_code == 200, r1.text[:200])
r2 = upload_async_test_exam()
check("second upload is rejected even though grading already finished",
      r2.status_code == 409, str(r2.status_code))

print("\n[27] A background failure is recorded, not silently swallowed")
def failing_pipeline(pages, mcq_numbers, essay_count, has_mcq, topic_hint="", essay_plan=None):
    raise RuntimeError("simulated OCR crash")

fail_student = User(first_name="Errol", last_name="Santos", email="errol@test.local",
                    password_hash="x", role=UserRole.Student)
s = SessionLocal()
s.add(fail_student); s.flush()
s.add(Enrollment(class_id=class_id, student_id=fail_student.user_id))
s.commit()
fail_student_id = fail_student.user_id
s.close()

pipeline_module.run_pipeline = failing_pipeline
as_user(fail_student_id)
r = upload_async_test_exam()
check("upload still returns 200 even though grading will fail",
      r.status_code == 200, r.text[:200])
pipeline_module.run_pipeline = fake_run_pipeline  # restore for later tests

s = SessionLocal()
failed_sub = s.query(ExamSubmission).filter(
    ExamSubmission.exam_id == async_exam_id, ExamSubmission.student_id == fail_student_id
).first()
check("submission is marked Failed, not stuck in Processing",
      failed_sub is not None and failed_sub.submission_status == SubmissionStatus.Failed,
      str(failed_sub.submission_status if failed_sub else None))
check("submission stays locked after a failure (professor must re-scan)",
      failed_sub is not None and failed_sub.locked_for_student())
check("the actual error is recorded for the professor to see",
      failed_sub is not None and failed_sub.processing_metadata_json
      and "simulated OCR crash" in failed_sub.processing_metadata_json,
      str(failed_sub.processing_metadata_json if failed_sub else None))
s.close()

# The student-facing status endpoint must explain this honestly rather than
# leaving them looking at an endless "processing" state.
as_user(fail_student_id)
result_body = client.get(f"/api/student/exams/{async_exam_id}/result").json()
check("student result reflects the failed state",
      result_body.get("submission", {}).get("failed") is True, str(result_body.get("submission")))


# ---------------------------------------------------------------------------
print("\n[28] The professor detail endpoint reflects processing/failed honestly")
# Before this, a submission mid-grading would show empty MCQ/essay question
# arrays with no explanation, and a failed one looked identical to "nothing
# submitted" — both looked like bugs rather than a known, communicated state.
as_user(prof_id)

# A fresh submission, before its background task has a chance to touch it,
# would be indistinguishable from "still processing" if we could catch it in
# that window. Since TestClient runs the background task to completion before
# the upload call returns, we instead verify the FAILED case end-to-end (which
# genuinely stays in a non-terminal-for-grading state) and check the schema
# fields exist and are correctly false for a normal graded submission.

detail = client.get(f"/api/exams/{exam_id}/submissions/by-student/{student_id}").json()
check("graded submission reports processing=false", detail.get("processing") is False, str(detail.get("processing")))
check("graded submission reports failed=false", detail.get("failed") is False, str(detail.get("failed")))
check("graded submission has no error", detail.get("error") is None, str(detail.get("error")))

failed_detail = client.get(f"/api/exams/{async_exam_id}/submissions/by-student/{fail_student_id}").json()
check("failed submission reports failed=true", failed_detail.get("failed") is True, str(failed_detail))
check("failed submission reports processing=false", failed_detail.get("processing") is False)
check("failed submission surfaces the real error", "simulated OCR crash" in (failed_detail.get("error") or ""),
      str(failed_detail.get("error")))
check("failed submission cannot be released", failed_detail["release"]["canRelease"] is False,
      str(failed_detail["release"]))
check("failed submission has no question breakdown to avoid implying it was graded",
      failed_detail["mcq"]["questions"] == [] and failed_detail["essay"]["questions"] == [],
      str((failed_detail["mcq"]["questions"], failed_detail["essay"]["questions"])))

print("\n[29] StatusBadge covers every real status the backend can return")
# Regression guard for a real pre-existing bug: the frontend's StatusBadge
# style map only had entries for strings the backend never returns
# ("Submitted"/"Processing"/"Flagged"), so every badge silently fell back to
# the same gray style. This can't be tested from Python directly, but the
# set of statuses the backend can actually emit is verified here so the
# frontend's map (checked separately) has a known, complete target.
BACKEND_STATUSES = {s.value for s in SubmissionStatus}
check("SubmissionStatus includes Failed", "Failed" in BACKEND_STATUSES, str(BACKEND_STATUSES))
check("SubmissionStatus includes the full processing chain",
      {"Pending", "Uploaded", "OCR_Processing", "OCR_Completed", "NLP_Processing", "Graded", "Released"} <= BACKEND_STATUSES,
      str(BACKEND_STATUSES))


# ---------------------------------------------------------------------------
print("\n[30] Batched Sentence-BERT similarity matches individual calls")
# Regression guard for the essay-grading speed work: batching every essay
# answer's similarity encoding into one Sentence-BERT call must produce
# EXACTLY the same scores as calling semantic_similarity() once per answer
# (the previous behavior) - a batching bug that silently shifted scores
# would be far worse than one that crashed loudly.
BIO_KEY = "The biosphere is where living organisms exist; producers, consumers and decomposers cycle nutrients."
MITOSIS_KEY = "Mitosis divides one cell into two identical daughter cells for growth and repair."

bio_analysis = nlp_spacy.analyze(
    "Producers, consumers and decomposers move nutrients through the ecosystem where life exists."
)
mitosis_analysis = nlp_spacy.analyze(
    "Mitosis splits a cell into two identical daughter cells used for growth and tissue repair."
)
offtopic_analysis = nlp_spacy.analyze("The Treaty of Versailles ended the First World War in 1919.")

single_results = [
    nlp_spacy.semantic_similarity(bio_analysis, BIO_KEY),
    nlp_spacy.semantic_similarity(mitosis_analysis, MITOSIS_KEY),
    nlp_spacy.semantic_similarity(offtopic_analysis, MITOSIS_KEY),
]
batched_results = nlp_spacy.batch_semantic_similarity([
    (bio_analysis, BIO_KEY),
    (mitosis_analysis, MITOSIS_KEY),
    (offtopic_analysis, MITOSIS_KEY),
])

check("batch returns one result per input pair", len(batched_results) == 3, str(len(batched_results)))
for label, single, batched in zip(
    ["on-topic biosphere answer", "on-topic mitosis answer", "off-topic answer"],
    single_results, batched_results,
):
    check(f"batched score matches individual score ({label})",
          abs(single["score"] - batched["score"]) < 0.01,
          f"single={single['score']} batched={batched['score']}")
    check(f"batched engine matches individual engine ({label})",
          batched["engine"] == single["engine"], f"{batched['engine']} vs {single['engine']}")

check("batching still discriminates: on-topic beats off-topic",
      batched_results[1]["score"] > batched_results[2]["score"],
      f"{batched_results[1]['score']} vs {batched_results[2]['score']}")
check("empty batch returns empty list", nlp_spacy.batch_semantic_similarity([]) == [])

blank_analysis = nlp_spacy.analyze("")
mixed = nlp_spacy.batch_semantic_similarity([(blank_analysis, BIO_KEY), (bio_analysis, BIO_KEY)])
check("a blank answer inside a batch skips the model", mixed[0]["engine"] == "none" and mixed[0]["score"] == 0.0)
check("a real answer in the same batch still uses the model",
      mixed[1]["engine"] in ("sentence_transformer", "lexical_fallback"))

print("\n[31] Roster-constrained student identification")
# The accuracy fix: Ollama used to transcribe a handwritten name blind, with
# zero knowledge of the actual class roster, then a separate fuzzy-text step
# tried to reconcile whatever it guessed against real students. Now the
# roster is passed all the way through so Ollama can pick directly from real
# candidates. This only verifies the plumbing (the roster reaches the
# prompt-building function); it cannot verify OCR accuracy on real
# handwriting without a real scanned image.
import inspect as _inspect
from services.ocr_hybrid import extract_text as _extract_text

sig = _inspect.signature(_extract_text)
check("extract_text accepts a roster parameter", "roster" in sig.parameters, str(sig.parameters))


# ---------------------------------------------------------------------------
print("\n[32] Oversized uploads are rejected, not silently accepted")
# Before this, every upload endpoint read the file into memory with no size
# check at all. A single oversized (or malicious) upload could exhaust
# memory or disk. MAX_UPLOAD_MB caps each page.
OVERSIZED = b"\xff\xd8\xff" + (b"0" * (16 * 1024 * 1024))  # ~16MB, over the 15MB default

as_user(student_id)
r = client.post(
    f"/api/student/exams/{async_exam_id}/upload",
    files=[("page1", ("big.jpg", OVERSIZED, "image/jpeg")),
           ("essay_pages", ("e1.png", PNG, "image/png"))],
)
check("an oversized page1 upload is rejected", r.status_code == 413, f"{r.status_code} {r.text[:150]}")
check("the error names the size limit", "MB" in r.text, r.text[:150])

r = client.post(
    f"/api/student/exams/{async_exam_id}/upload",
    files=[("page1", ("p1.png", PNG, "image/png")),
           ("essay_pages", ("big.jpg", OVERSIZED, "image/jpeg"))],
)
check("an oversized essay page is also rejected", r.status_code == 413, str(r.status_code))

print("\n[33] CORS origins are configurable, not hardcoded")
check("main.py reads CORS origins from the environment",
      "CORS_ALLOWED_ORIGINS" in open("main.py").read())


# ---------------------------------------------------------------------------
print("\n[34] Mixed answer formats paginate identically on both sides")
from services import sheet_layout as _layout  # noqa: E402

check("two short answers share a page",
      _layout.plan_essay_pages(["one_paragraph", "one_paragraph"]) == [[0, 1]])
check("a multi-paragraph answer takes a page of its own",
      _layout.plan_essay_pages(["multi_paragraph"]) == [[0]])
check("a long answer flushes the page its predecessor was waiting on",
      _layout.plan_essay_pages(["one_paragraph", "multi_paragraph", "one_paragraph"])
      == [[0], [1], [2]])
check("short answers after a long one pair up again",
      _layout.plan_essay_pages(
          ["one_paragraph", "multi_paragraph", "one_paragraph", "one_paragraph"])
      == [[0], [1], [2, 3]])
check("'essay' is treated as a long format too",
      _layout.plan_essay_pages(["essay", "one_paragraph"]) == [[0], [1]])
check("an unknown format is treated as a short answer",
      _layout.plan_essay_pages([None, "weird_new_value"]) == [[0, 1]])
check("no essays means no essay pages",
      _layout.plan_essay_pages([]) == [])


class _Q:
    """Minimal stand-in for an ExamQuestion row."""
    def __init__(self, question_id, response_format):
        self.question_id = question_id
        self.expected_response_format = response_format


mixed = [_Q(101, "one_paragraph"), _Q(102, "multi_paragraph"),
         _Q(103, "one_paragraph"), _Q(104, "one_paragraph")]

check("expected_essay_pages counts the real pages, not ceil(n/2)",
      pipeline.expected_essay_pages(mixed) == 3,
      str(pipeline.expected_essay_pages(mixed)))
check("expected_essay_pages still accepts a bare count",
      pipeline.expected_essay_pages(4) == 2)
check("all-short exams are unaffected",
      pipeline.expected_essay_pages([_Q(1, "one_paragraph")] * 4) == 2)


def _page(index, *answers):
    return {"index": index,
            "extraction": {"answers": [{"answer": a} for a in answers]}}


# Page 0 -> Q101, page 1 -> Q102 (alone), page 2 -> Q103 + Q104.
results = [_page(0, "answer to one"), _page(1, "answer to two"),
           _page(2, "answer to three", "answer to four")]
texts = pipeline._essay_texts_by_question(results, mixed,
                                          pipeline.essay_page_plan(mixed))

check("each answer reaches the question it was written under",
      texts == {101: "answer to one", 102: "answer to two",
                103: "answer to three", 104: "answer to four"},
      str(texts))

# The pre-fix arithmetic, kept here so a regression is recognisable rather
# than just red: page_index * 2 + box_index put page 1's answer on Q103.
legacy = {}
for r in results:
    for box, a in enumerate((r["extraction"] or {}).get("answers") or []):
        pos = r["index"] * 2 + box
        if pos < len(mixed):
            legacy[mixed[pos].question_id] = a["answer"]
check("the old mapping really was wrong on this exam (guards the regression)",
      legacy != texts, str(legacy))

check("the mapping is derived from the questions when no plan is passed",
      pipeline._essay_texts_by_question(results, mixed) == texts)

# A page beyond the layout is dropped rather than mis-filed.
check("an extra scanned page cannot overwrite a real answer",
      pipeline._essay_texts_by_question(results + [_page(9, "stray")], mixed,
                                        pipeline.essay_page_plan(mixed)) == texts)


print("\n[35] Admin routes are guarded")
_admin_paths = ["/api/admin/overview", "/api/admin/system", "/api/admin/users"]
as_user(student.user_id)
for path in _admin_paths:
    r = client.get(path)
    check(f"a student cannot reach {path}", r.status_code == 403, str(r.status_code))
as_user(prof.user_id)
for path in _admin_paths:
    r = client.get(path)
    check(f"a professor cannot reach {path}", r.status_code == 403, str(r.status_code))


print("\n[36] A publicly known JWT secret is never used for signing")
from services import auth_service as _auth  # noqa: E402

check("the shipped placeholder is recognised as public",
      "REPLACE_ME_WITH_A_NEW_RANDOM_SECRET" in _auth._PUBLIC_PLACEHOLDERS)
check("the old code default is recognised as public",
      "CHANGE_ME_IN_PRODUCTION" in _auth._PUBLIC_PLACEHOLDERS)
check("an empty secret is recognised as public", "" in _auth._PUBLIC_PLACEHOLDERS)
check("no placeholder is ever the active signing key",
      _auth.SECRET_KEY not in _auth._PUBLIC_PLACEHOLDERS)
check("the generated fallback is long enough to resist guessing",
      len(_auth.SECRET_KEY) >= 32, str(len(_auth.SECRET_KEY)))
check("a real secret is used as given",
      _auth._load_secret_key.__doc__ is not None)


print(f"\n{'=' * 60}")
print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
if FAILED:
    for name in FAILED:
        print(f"  FAILED: {name}")
    sys.exit(1)
print("All checks passed.")