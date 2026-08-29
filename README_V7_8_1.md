# ESSCAN V7.8.1 — Marker-Aligned Hybrid Scanner

This release is a focused scanner correction built from V7.7/V7.8. It keeps the existing FastAPI + MySQL + EasyOCR V5.2 + OpenCV OMR + Ollama Qwen 2.5-VL 3B pipeline.

## V7.8.1 fixes

- Corrects live four-marker selection so the detector favors the four printed black registration squares instead of unrelated dark rectangles.
- Uses the known ESSCAN page aspect ratio and equal marker sizing when selecting candidates.
- Maps backend detector coordinates through the actual Android camera/video `object-contain` rectangle before drawing the overlay.
- Uses the same `CameraScanner` for Professor and Student upload flows.
- Student camera passes the selected exam ID and page number to live detection.
- Keeps high-resolution final capture for downstream OCR/OMR.

## Scanner behavior

- Orange: fewer than four marks detected.
- Green: four marks detected.
- Auto-capture still requires the backend readiness checks plus stable frames.
- The overlay should sit directly on the four printed registration squares.

## Student page numbering

- Page 1 / MCQ: `1`
- Essay page 1: `2`
- Essay page 2: `3`
- Additional essay pages continue sequentially.

## Backend setup (Python 3.11)

```powershell
cd .\backend
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

Copy/configure `backend/.env`. Confirm MySQL is running and Ollama exposes `qwen2.5vl:3b` at `http://localhost:11434`.

Start FastAPI:

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Frontend setup

```powershell
cd .\frontend
npm install
npm run dev -- --host 0.0.0.0
```

The Vite configuration uses HTTPS and proxies `/api` to `http://192.168.1.20:8000`.

On Android Chrome, open:

`https://192.168.1.20:5173`

Accept the local development certificate warning if Chrome shows one, then allow camera access.

## Frontend environment

`frontend/.env` should contain:

```env
VITE_API_BASE_URL=/api
```

Do not replace this with the backend URL while using the HTTPS Vite proxy.

## Main scanner files

- `frontend/src/components/common/CameraScanner.jsx`
- `frontend/src/pages/Professor/Upload/index.jsx`
- `frontend/src/pages/student/StudentUpload.jsx`
- `backend/services/omr.py`
- `backend/services/scanner.py`
- `backend/routers/uploads.py`

## AI roles

- OpenCV: page alignment + OMR
- EasyOCR V5.2: primary handwriting OCR
- Qwen 2.5-VL 3B: secondary OCR verification/correction where configured
- SpaCy/Sentence-BERT: downstream language/semantic analysis
