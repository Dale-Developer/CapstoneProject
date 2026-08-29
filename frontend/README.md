# ESSCAN Frontend

This version keeps the existing authentication experience and ESSCAN Audiowide topbar branding while polishing the professor PWA layout for responsive use and future FastAPI/MySQL integration.

## Main UI improvements

- Dashboard and Exams use the same responsive container system.
- Desktop content uses the available width more effectively instead of leaving large side margins.
- Class cards and exam cards preserve the original visual direction while adapting from mobile to wide desktop.
- ClassView, StudentsList, ExamView, ExamStudentSubmission, and ExamSubmissionDetails now use the same page spacing, headers, cards, status badges, and responsive grids.
- Ranking has a responsive desktop table and mobile ranking cards, plus summary statistics, filters, and top performers.
- Upload is available from the sidebar and mobile scan button.
- Upload supports multiple answer sheets and requires at least two files.
- Camera capture uses the browser MediaDevices API and prefers the rear/environment camera on mobile devices.
- The topbar plus button remains Create New Class.
- Login/signup files were not redesigned.

## FastAPI preparation

Set `VITE_API_BASE_URL` in `.env` using `.env.example` as a template.

The frontend API layer is in `src/api/` and is intentionally separated from the page components. Uploads are prepared as `multipart/form-data` for a FastAPI endpoint such as:

`POST /api/uploads/submissions`

Expected fields:

- `exam_id`
- `source`
- `files` (multiple UploadFile values)

The frontend does not connect directly to MySQL. FastAPI should remain the API/service layer between the PWA and MySQL.

## Run

```bash
npm install
npm run dev
```

## Suggested backend architecture

```text
ESSCAN PWA (React)
        |
        | HTTP / JSON / multipart
        v
FastAPI
        |
        +--> MySQL
        |
        +--> OCR / NLP processing layer
```
