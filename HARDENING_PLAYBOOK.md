# ESSCAN — Complete Hardening Playbook

Two phases, matching what we discussed: do the cheap stuff now, save the
heavier items for once the feature set stops changing. Phase 1 items below
are already implemented in this zip where they're code changes — you just
need to run the setup steps. Phase 2 is a checklist for later; nothing in
Phase 2 has been built yet, on purpose.

---

# PHASE 1 — Do Now

## A. Git version control

```powershell
cd "C:\Users\Z82060\Desktop\(MAIN) Capstone Project\ESSCAN FINALIZATION\V7.9.6"

git init
git add .
git commit -m "V7.9.6 — baseline: async processing, rubric engine, SBERT V3, speed work"
```

If `git` isn't recognized, install it first: https://git-scm.com/download/win
(default options are fine), then reopen PowerShell.

**A `.gitignore` is already included** in this zip — it keeps `venv/`,
`node_modules/`, `.env` (your real secrets), student uploads, and the large
model weight files (`.pth`/`.safetensors`) out of git. Those model files are
too large for a normal git repo anyway; keep distributing them the way we
have been (a separate zip/folder), or see Phase 2's Docker section for a
cleaner way to handle that long-term.

Verify `.env` really got excluded — this matters, it has your JWT secret:

```powershell
git status
```

You should **not** see `backend/.env` in the list of tracked files. If you
do, you added it before the `.gitignore` existed:

```powershell
git rm --cached backend/.env
git commit -m "Remove .env from tracking"
```

**From now on, commit after each meaningful change:**

```powershell
git add .
git commit -m "short description of what changed"
```

This alone — a real commit history — is something a capstone panel will
generally expect to see.

## B. Automated backups

A backup script is included: `backend\backup_database.ps1`. It dumps the
MySQL database and zips the uploads folder into `backend\backups\`, and
automatically deletes anything older than 14 days so it won't fill your
disk unattended.

### One-time test run

```powershell
cd backend
.\backup_database.ps1
```

If your XAMPP MySQL root user has no password (the default), you don't need
to pass anything. If it does:

```powershell
.\backup_database.ps1 -DbPassword "yourpassword"
```

Confirm it worked:

```powershell
Get-ChildItem .\backups -Recurse
```

You should see a `.zip` under `backups\database\` and one under
`backups\uploads\`.

### Automate it (Windows Task Scheduler)

1. Open **Task Scheduler** (search it in the Start menu).
2. **Create Task...** (not "Basic Task" — you need the extra options).
3. **General tab**: name it `ESSCAN Backup`. Check "Run whether user is
   logged on or not" if you want it to run even when you're not signed in.
4. **Triggers tab** → **New...** → Daily, pick a time when the app is idle
   (e.g., 2:00 AM).
5. **Actions tab** → **New...**:
   - Program/script: `powershell.exe`
   - Add arguments:
     ```
     -ExecutionPolicy Bypass -File "C:\Users\Z82060\Desktop\(MAIN) Capstone Project\ESSCAN FINALIZATION\V7.9.6\backend\backup_database.ps1" -DbPassword "yourpassword"
     ```
   - Start in: `C:\Users\Z82060\Desktop\(MAIN) Capstone Project\ESSCAN FINALIZATION\V7.9.6\backend`
6. **OK**, enter your Windows password if prompted.

Test it fired correctly by right-clicking the task → **Run**, then check
`backups\` again.

**Do not commit the `backups\` folder to git** — it's not in `.gitignore`
by default since backup storage location is a personal choice; either add
`backend/backups/` to `.gitignore` yourself, or keep backups on a separate
drive/cloud folder entirely (safer anyway — a backup living next to what it
backs up doesn't help if the disk fails).

## C. Upload size limits — already implemented

Every upload endpoint now rejects files over a configurable limit instead of
accepting anything of any size. Nothing for you to do here except know the
setting exists:

```dotenv
# backend/.env
MAX_UPLOAD_MB=15
```

Raise it if your camera photos are consistently larger and getting
rejected; a scanned answer sheet is realistically a few MB, so 15 has
headroom. This is enforced server-side now — verified by an automated test
that a 16MB upload gets a `413` response.

## D. CORS is now environment-driven — already implemented

`main.py` no longer hardcodes dev origins. It reads from `.env`:

```dotenv
# backend/.env — change this per environment, never touch main.py
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://192.168.1.20:5173
```

**When you actually deploy**, this line becomes your production frontend's
real domain instead of localhost/LAN addresses — that's the only change
needed, no code edit. Keep it a comma-separated allowlist, never `*` — an
allowlist is already the right pattern, just point it at the real domain
when the time comes.

---

# PHASE 2 — Do Later (checklist, not built yet)

Come back to this once your grading pipeline's behavior is final — not
mid-iteration. Nothing below has been implemented in this zip.

## A. Docker containerization

**What it involves, roughly, when you're ready:**
1. A `Dockerfile` for the backend: Python base image, install
   `requirements.txt`, copy code (model weights mounted as a volume rather
   than baked into the image — they're too large and don't change often).
2. A `docker-compose.yml` wiring together: the FastAPI backend, MySQL, and
   optionally Ollama as its own service.
3. The frontend either gets its own container (nginx serving the built
   `dist/`) or is built and served by the same reverse proxy as the backend.
4. Environment variables (`.env`) get passed into containers via
   `docker-compose.yml`'s `environment:` block or an env file — never baked
   into the image.

I can build this out fully when you're ready — it's a genuinely valuable
piece for your capstone (directly demonstrates the Portability quality
characteristic), just say so in a future message.

## B. Load / stress testing

Tools worth knowing about (free, no need to buy anything):
- **Locust** (Python, matches your stack) — simulate N professors uploading
  concurrently, watch response times and error rates.
- **Apache Bench (`ab`)** — quick and dirty single-endpoint load test.
- **k6** — more modern, good for scripted realistic user flows.

What to actually test once you get here: simulate scanning 30 students
back-to-back (matching your real use case) and confirm the async processing
holds up — check that the background task queue doesn't fall arbitrarily
far behind, and that memory doesn't climb unbounded over the batch.

## C. Rate limiting

When you're ready, `slowapi` (a FastAPI-native wrapper around the
well-established `limits` library) is the natural fit — a few lines per
endpoint, no new infrastructure required. Priority endpoints once you get
here: `/api/auth/login` (brute-force protection) and `/api/uploads/scan-preview`
(hit repeatedly during live camera scanning — needs a generous per-second
limit, not a strict one, since that's its normal usage pattern).

## D. Secret rotation

Do this **last**, right before you actually go live — no benefit to
rotating early since you'd likely rotate again before deployment anyway.
When that time comes:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into `JWT_SECRET_KEY` in your production `.env` (never the
same value as your dev `.env` — anyone who has seen the dev value, including
in any zip or screenshot you've shared, should not be able to forge
production tokens).

---

# Verify Phase 1 end to end

```powershell
cd backend
python tests_v7_9.py
```

**Expect: `PASSED: 158   FAILED: 0`** (156 with `SBERT_ENABLED=false`).

New in this run: `[32]` proves an oversized upload is actually rejected
with a `413`, not just capped in theory; `[33]` confirms CORS reads from
the environment.
