# ESSCAN V7.9.4 — Start Here

Everything — source code, the grading engine, the fine-tuned SBERT V3 model,
and your EasyOCR V5.2 weights — is already inside this zip. Nothing else to
download or copy.

---

## What changed in this version

**1. Uploads no longer block scanning the next student.**
Previously, uploading an answer sheet waited for the *entire* OCR/OMR/essay-
grading pipeline to finish before the request returned — several seconds per
sheet, longer under Ollama verification. Now the endpoint saves the files,
locks the submission, and returns in milliseconds; grading runs afterward in
a background task. The professor Upload page resets immediately and shows a
live "Recently scanned" panel that updates on its own as each sheet finishes.
The student upload page behaves the same way.

A new `Failed` status exists for the rare case where background grading
throws — the sheet is marked failed with the real error recorded, rather than
sitting silently in "processing" forever. Migration `009` adds this.

**2. Essay grading detail pages are complete.**
`ExamSubmissionDetails.jsx` and `ExamStudentSubmission.jsx` now correctly
handle three real states — still processing, failed, and graded — instead of
assuming grading had already finished. A submission that's mid-grading or
failed shows an honest banner instead of an empty or misleading breakdown.

Along the way, a real pre-existing bug was found and fixed: `StatusBadge`'s
style map only had entries for strings the backend never actually returns
(`Submitted`/`Processing`/`Flagged`) — every status badge in the app was
silently falling back to the same gray style regardless of the true status.
It's now wired to the actual status vocabulary, with `Failed` shown in red.

A second bug, caught by a test written for this: a *failed* submission was
still returning its half-written per-question rows as if graded, showing
synthesized "blank/incorrect" answers for a sheet that was never scored.

**3. The exam view has one clear scan entry point.**
Added a "Scan answer sheet" button to the exam page header that jumps
straight to the Upload page with that exam pre-selected — no need to find it
again in the dropdown.

> I could not find a second "Upload answer sheet" button anywhere in the
> codebase after tracing every reference twice. The only upload entry point
> that existed before this change was the global sidebar link (desktop) and
> floating action button (mobile) — which are mutually exclusive by screen
> size and were never both visible at once. If you're still seeing two after
> this update, please send a screenshot; I'll find it immediately from that.

**4. Responsive audit.**
Went through every page and component. The good news: this app was already
built with proper responsive patterns throughout (breakpoint prefixes,
`overflow-x-auto` table wrappers, a dedicated mobile card view on the
Ranking page, `min-w-0`/`truncate`/`line-clamp` used correctly almost
everywhere). Two real issues were found and fixed:
- Three section headers in the exam-creation form (`CreateExam.jsx`) could
  crowd on very narrow phones — added `flex-wrap`.
- Each rubric criterion row packed a 4-line description block against a
  fixed 112px weight input with no wrap point, crushing the text into a
  ~78px column on a phone. It now stacks vertically below the `sm`
  breakpoint and goes back to a single row on larger screens.

Also updated two labels that had gone stale from earlier changes: the essay
section description used to say "one paragraph" and "future AI-assisted
grading" — it now correctly says the format is configurable per question and
grading is live via spaCy + Sentence-BERT.

---

## Setup

### 1. Confirm the model files are present

```powershell
cd backend
Test-Path .\ai_models\ESSCAN_AAA_SBERT_ASAP_V3_FINAL\model\modules.json
Test-Path .\ai_models\easyocr_v5_2\model\handwriting_finetune_v5_2.pth
```

Both must print `True` — they're already inside this zip.

### 2. Python environment (first run only)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 3. Database

If upgrading from an earlier V7.9.x database, only migration `009` is new:

```powershell
mysql -u root -p automate_assessment_application < migrations\009_async_processing_failed_status.sql
```

For a fresh database, apply `002` through `009` in order (see the
`migrations/` folder).

### 4. Run

```powershell
# Terminal 1
cd backend
.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2
cd frontend
npm install
npm run dev
```

### 5. Verify

```powershell
cd backend
python tests_v7_9.py
```

**Expect: `PASSED: 142   FAILED: 0`** with `SBERT_ENABLED=true` in `.env`
(the default). This covers the rubric engine, SBERT grading, the async
processing pipeline including a simulated background failure, and every
permission/locking rule.

```powershell
curl http://localhost:8000/api/health/ai
```

Wait 30–60 seconds after startup for model warmup, then confirm
`sentenceBert.loaded: true` and `easyocr.available: true`.

---

## Files changed this version

```
backend/models/exam_submission.py             Failed status
backend/services/submission_pipeline.py       background processing entry point
backend/routers/uploads.py                    fast-return + background dispatch
backend/routers/student.py                    fast-return + background dispatch
backend/routers/exams.py                      processing/failed fields on detail endpoint
backend/migrations/009_*.sql                  Failed status migration
backend/tests_v7_9.py                         +24 checks for async processing (142 total)

frontend/src/components/prof/PageShell.jsx           StatusBadge fix
frontend/src/pages/Professor/Upload/index.jsx         fast-return UX, recent-uploads panel
frontend/src/pages/Professor/Exams/ExamView.jsx       Failed status, scan button
frontend/src/pages/Professor/Exams/ExamStudentSubmission.jsx   processing/failed banners
frontend/src/pages/Professor/Exams/ExamSubmissionDetails.jsx   processing/failed guard
frontend/src/pages/Professor/Exams/CreateExam.jsx     responsive fixes, stale copy
frontend/src/pages/student/StudentUpload.jsx          fast-return UX, processing/failed states
frontend/src/pages/student/StudentExamView.jsx        processing/failed states
frontend/src/pages/student/StudentResult.jsx          processing/failed states
```
