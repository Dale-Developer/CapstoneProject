# ESSCAN Frontend — FastAPI + Printable Exam Sheet

This frontend is wired to the supplied FastAPI backend.

## Backend endpoints

### Authentication
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

### Classes
- `GET /api/classes`
- `POST /api/classes`
- `GET /api/classes/{class_id}`
- `PUT /api/classes/{class_id}`
- `GET /api/classes/{class_id}/students`
- `POST /api/classes/join`

### Examinations
- `GET /api/exams`
- `POST /api/exams`
- `GET /api/exams/{exam_id}`
- `PUT /api/exams/{exam_id}`
- `GET /api/exams/{exam_id}/submissions`
- `GET /api/exams/{exam_id}/pdf`

## Printable answer-sheet behavior

When a professor creates or edits an exam, the frontend saves the exam through FastAPI and then downloads the generated printable answer sheet.

The PDF uses Philippine long bond paper (8.5 × 13 inches) and follows the supplied reference format:

- QR code at the top
- `[ PAGE N ]`
- `SUBJECT - EXAM TITLE`
- Student Name / Student No. / Section fields on page 1
- Multiple-choice answer bubbles A-E
- 30 MCQs per column, 60 per MCQ page
- Essay answer areas, four per page
- Additional pages are generated automatically if the exam has more than 60 MCQs or more than 4 essay questions

The QR code currently contains `ESSCAN|EXAM|<exam_id>` so the scanned sheet can be associated with its exam later.

## Local setup

### Backend

From `backend`:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

The backend automatically creates the new `exam_questions` and `exam_rubrics` tables when they are missing. It also adds `exams.exam_subject` to an older development database when necessary.

### Frontend

Copy `.env.example` to `.env`:

```env
VITE_API_BASE_URL=http://localhost:8000/api
```

Then:

```powershell
npm install
npm run dev
```

## Database

The supplied backend uses the existing `automate_assessment_application` MySQL/MariaDB database.

A manual migration is also included at:

`backend/migrations/003_add_exam_questions_and_printable_sheet.sql`

The startup schema check is provided for local development; for production, use the SQL migration as part of your deployment process.
