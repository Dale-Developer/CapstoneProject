# ESSCAN V7.9.7

Merge-ready. This zip mirrors your project's folder structure, so extracting
it over `V7.9.6\` puts every file in the right place. It contains ONLY files
that are new or changed — nothing else is touched.

Back up first, then extract over the project root (the folder holding
`backend\` and `frontend\`) and choose "replace files in destination".

---

## Do this BEFORE extracting

`users.role` is a MySQL ENUM. Widening the column has to happen before the
code tries to store `Admin`, or creating an administrator fails with a
data-truncation error.

```powershell
cd "C:\Users\Z82060\Desktop\(MAIN) Capstone Project\ESSCAN FINALIZATION\V7.9.6\backend"
mysql -u root -p automate_assessment_application < migrations\011_admin_role.sql
```

(Copy `011_admin_role.sql` into `backend\migrations\` first, or run it from
this zip.)

Verify:

```sql
SHOW COLUMNS FROM users LIKE 'role';
-- enum('Professor','Student','Admin')
```

---

## After extracting

```powershell
cd "C:\Users\Z82060\Desktop\(MAIN) Capstone Project\ESSCAN FINALIZATION\V7.9.6\backend"
Get-ChildItem -Path . -Filter __pycache__ -Recurse -Directory | Remove-Item -Recurse -Force
```

Add these to `backend\.env` (compare against `env_final.txt` in this zip for
the full recommended file — it is NOT copied automatically, so your secrets
are never overwritten):

```
OCR_MIN_PLAUSIBILITY=0.80
OCR_PLAUSIBILITY_MARGIN=0.15
OCR_PLAUSIBILITY_MIN_LEN=3
```

Restart uvicorn. Vite reloads the frontend by itself.

### Verify

```powershell
python tests_v7_9.py
Select-String -Path "services\ocr_hybrid.py" -Pattern "_lexical_plausibility" | Select-Object -First 1
Select-String -Path "routers\admin.py"       -Pattern "require_admin"         | Select-Object -First 1
```

158 checks should still pass.

### Create the first administrator

```powershell
python admin.py create --email you@school.edu --first Your --last Name --role Admin
```

Omit `--password` and it prompts, so it never enters your shell history.
Log in from the normal form on either tab; you land on `/Admin/users`.

---

## Contents

### Fixed (OCR extraction)

| File | Location |
|---|---|
| `sheet_layout.py` | `backend\services\` — NEW, shared answer-sheet geometry |
| `exam_pdf.py` | `backend\services\` |
| `ocr_hybrid.py` | `backend\services\` |
| `submission_pipeline.py` | `backend\services\` |
| `ExamStudentSubmission.jsx` | `frontend\src\pages\Professor\Exams\` |

### Added (administration)

| File | Location |
|---|---|
| `011_admin_role.sql` | `backend\migrations\` |
| `admin.py` | `backend\routers\` — the API router |
| `auth.py` | `backend\routers\` |
| `user.py` | `backend\models\` |
| `user.py` | `backend\schemas\` |
| `auth_service.py` | `backend\services\` |
| `main.py` | `backend\` |
| `adminApi.js` | `frontend\src\api\` |
| `AdminLayout.jsx` | `frontend\src\layouts\` |
| `AdminSidebar.jsx` | `frontend\src\components\admin\` |
| `Users\index.jsx` | `frontend\src\pages\Admin\Users\` |
| `System\index.jsx` | `frontend\src\pages\Admin\System\` |
| `App.jsx` | `frontend\src\` |

### Added (diagnostic tools, all in `backend\`)

| File | What it does |
|---|---|
| `admin.py` | CLI account management. NOT the same file as `routers\admin.py`. |
| `diagnose_ocr.py` | Runs the real pipeline on one image, dumps the crop |
| `diagnose_grading.py` | Grades one answer twice: as written vs as OCR'd |
| `sweep_ocr.py` | Scores 8 EasyOCR configurations against ground truth |
| `sweep_vision.py` | Compares Ollama vision models on one crop |

---

## What changed in 7.9.7

**Answer-sheet geometry is now shared.** `exam_pdf` (which draws) and
`ocr_hybrid` (which crops the scan back out) import the same
`sheet_layout` module. They previously held separate copies of the page
coordinates and had drifted apart, which cost the first written line of every
answer and split two-answer pages across the wrong questions.

**Answer boxes stack.** `_draw_essay_answer_page` ignored its loop index and
drew every box at the same full-page rectangle. Sheets with two answers on a
page must be reprinted; single-answer pages are unchanged and still scan.

**Clustering no longer deletes text.** Raw IoU 0.25 with no size guard merged
genuinely different lines of handwriting, and a cluster yields one winner.
Now 0.50 with a 2.8x area guard.

**`page1_path` points at the right file.** `"_page_1."` is a substring of
`"_essay_page_1."`, so the filename test matched both and recorded the essay
image as page 1.

**The vision verifier fails loudly.** A bare `except: return ""` made a
timeout, a refused connection and a crashed runner all look identical. The
reason and elapsed time are now recorded and shown.

**A lexical gate replaces the confidence gate.** EasyOCR confidence does not
track accuracy: measured on a real scan it read 0.6133 on output that was
40.6% character-accurate. The fraction of output that is real English words
scored 8.3% on the same text — close to the true 8.7% word accuracy. That is
now what decides whether to ask Ollama for a second opinion, and which
transcription wins.

**Administration.** A third role, a guarded API and an in-app interface for
accounts and service health.

---

## Still open

* `_essay_texts_by_question` maps answers with
  `page_index * ESSAYS_PER_PAGE + box_index`, assuming 2 answers per page. But
  `multi_paragraph` questions get a dedicated page, so any exam mixing formats
  misaligns answers to questions. Not fixed.
* The QR code (`ESSCAN|EXAM|{id}`) is drawn but never decoded. Decoding it
  would let the pipeline identify pages itself instead of trusting upload
  order.
* `tests_v7_9.py` has no coverage for the admin routes.
* Measured OCR accuracy on real handwriting is 40.6% characters / 8.7% words.
  `sweep_ocr.py` has not been run yet; that is the remaining tuning step, and
  a daylight photo with a darker pen is likely worth more than any parameter.
