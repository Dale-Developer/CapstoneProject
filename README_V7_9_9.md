# ESSCAN V7.9.9 — PWA, one-line branding, JWT hardening

Includes everything from V7.9.8. If you have not merged that one, this
supersedes it — merge this instead.

Extract over the project root (the folder holding `backend\` and `frontend\`)
and replace files in destination. No database migration.

---

## Do these three things after extracting

### 1. Install the new frontend dependency

```powershell
cd "...\frontend"
npm install
```

`vite-plugin-pwa@^1.3.0` was added to `package.json`. It declares support for
Vite `^8.0.0`, which matches your `^8.0.12`.

### 2. Add the new lines to `frontend\.env`

`.env.example` is shipped rather than `.env`, so your file is not overwritten.
Add:

```
VITE_APP_NAME=ESSCAN
VITE_APP_SHORT_NAME=ESSCAN
VITE_APP_THEME_COLOR=#462776
VITE_BACKEND_TARGET=http://192.168.93.19:8000
```

Use whatever address the backend is actually on. Restart Vite afterwards —
`index.html` and the manifest are generated at startup, so a hot reload will
not pick up changes to these.

### 3. Set a real JWT secret

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the result into `JWT_SECRET_KEY` in `backend\.env`. See the security
section below for why this is not optional.

Then:

```powershell
cd "...\backend"
Get-ChildItem -Path . -Filter __pycache__ -Recurse -Directory | Remove-Item -Recurse -Force
python tests_v7_9.py
```

**182 checks should pass.**

---

## Progressive Web App

The frontend is now installable. On Android and desktop Chrome the browser
offers to install it; on iOS it is Share -> Add to Home Screen. It launches
full-screen with no browser chrome, which is the real win for a professor
holding a phone over an answer sheet.

Verified by building: `vite build` emits `dist/manifest.webmanifest`,
`dist/sw.js` and a 19-entry precache.

### The certificate is the catch

`@vitejs/plugin-basic-ssl` issues a self-signed certificate. Your camera works
over it because `getUserMedia` is satisfied once you click through the browser
warning. **Service workers are stricter** — browsers refuse to register one on
an origin with a certificate error, and without a registered service worker
there is no install prompt and no offline shell.

The app still works normally in that state; the failure is silent. A warning is
logged to the browser console explaining it (see `PWAUpdatePrompt.jsx`).

To actually install it you need a trusted certificate:

* **Cloudflare Tunnel** — free, real public hostname, works from any phone.
  Best if panelists will test on their own devices.
* **Tailscale** — valid certificate on a `.ts.net` name, private to devices you
  add.
* **mkcert** — local CA installed on the phone. Keeps everything on the LAN but
  is awkward to walk someone else through.

`http://localhost:5173` on a computer works without any of this — localhost is
always a secure context.

### What is and is not cached

The app shell is precached, so the app opens instantly and does not white-screen
on a weak connection. **Nothing under `/api` is ever cached.** `/api` is on a
`NetworkOnly` route and in `navigateFallbackDenylist`, verified present in the
generated `sw.js`.

This is deliberate and worth not undoing. A professor watches a submission move
from Processing to Graded by polling. One stale cached response makes grading
look stuck, and it presents as a backend fault with nothing in the backend logs.

Offline, the app tells the user it is offline. It cannot do more than that:
scanning is capture -> upload -> EasyOCR -> Ollama -> SBERT, all server-side.
Queuing captures in IndexedDB for Background Sync is a real feature but a
separate piece of work — a queued upload firing an hour later can hit the `409`
for an already-graded submission, and that needs its own UI and conflict
handling.

### Updates

`registerType: 'prompt'`, not `'autoUpdate'`. When a new bundle is deployed the
user gets a small "A new version is ready — Reload" bar rather than having the
app swapped out mid-scan. Without any prompt, an installed PWA keeps running
whatever was cached on first install, which surfaces as API calls failing in
ways the backend cannot explain.

### iOS note

`getUserMedia` inside an installed standalone PWA only works from iOS 16.4
onward. Below that the camera fails in the installed app while working fine in
Safari. Check whichever iPhone you demo on.

---

## Renaming the application is now one line

`VITE_APP_NAME` in `frontend\.env` drives the tab title, the login and signup
screens, both topbars, and the PWA manifest and install name. `APP_NAME` in
`backend\.env` drives the answer-sheet footer and the PDF document title.

I tested this by renaming to "Scriptura" and rebuilding: the manifest, the
`<title>` and the JS bundle all changed, with no source edits. Then reverted to
ESSCAN, since you have not told me a new name.

The logo is one file, `frontend\src\assets\mainLogo.png`, imported only by
`src\branding.js` now. Replace it and all three on-screen appearances follow.
Then regenerate the icons:

```powershell
cd "...\frontend"
python - <<'PY'
from PIL import Image
src = Image.open('src/assets/mainLogo.png').convert('RGBA')
for size in (192, 512):
    c = Image.new('RGBA', (size, size), (0,0,0,0))
    l = src.copy(); l.thumbnail((size, size), Image.LANCZOS)
    c.paste(l, ((size-l.width)//2, (size-l.height)//2), l)
    c.save(f'public/pwa-{size}x{size}.png')
c = Image.new('RGBA', (512,512), (255,255,255,255))
l = src.copy(); l.thumbnail((317,317), Image.LANCZOS)
c.paste(l, ((512-l.width)//2, (512-l.height)//2), l)
c.save('public/pwa-maskable-512x512.png')
c = Image.new('RGBA', (180,180), (255,255,255,255))
l = src.copy(); l.thumbnail((147,147), Image.LANCZOS)
c.paste(l, ((180-l.width)//2, (180-l.height)//2), l)
c.convert('RGB').save('public/apple-touch-icon.png')
PY
```

The maskable icon keeps the logo inside the 80% safe zone because Android crops
icons to the launcher's shape; the Apple icon is opaque because iOS composites
transparency onto black.

`frontend\public\favicon.svg` is separate and unchanged.

**One thing not to rename:** `ESSCAN|EXAM|{id}` in `exam_pdf.py` is the QR
payload, a machine format. Nothing decodes it yet, but a future decoder has to
match already-printed sheets exactly, so it is deliberately not derived from
`APP_NAME`. Same for `ai_models\ESSCAN_AAA_SBERT_ASAP_V3_FINAL\`, which is a
path in `SBERT_MODEL_PATH` — renaming the folder makes SBERT fail *soft* and
grading continues on the lexical fallback with different numbers.

There is still no admin UI for branding. That would need a settings table, an
API pair and a React context; the configuration approach above gets the same
result for a rename without the extra surface.

---

## Security: the JWT secret

**Correcting something I got wrong earlier.** I previously said your `.env`
contained a real `JWT_SECRET_KEY` and `DB_PASSWORD` that had been exposed and
needed rotating. That was wrong — I had masked both when reading the file and
assumed they were live. `DB_PASSWORD` is empty and `JWT_SECRET_KEY` is the
literal string `REPLACE_ME_WITH_A_NEW_RANDOM_SECRET`. No real credential was
leaked.

The actual finding is different, and worse. `auth_service.py` signed every token
with that placeholder, falling back to `CHANGE_ME_IN_PRODUCTION` when unset.
Both strings are public. A JWT payload carries the user id and role, so anyone
who has seen this repository could mint a valid admin token in a few lines of
script. That is a hosting blocker, not a tidiness issue.

`_load_secret_key()` now refuses to sign with any known placeholder. If
`JWT_SECRET_KEY` is unset or still a placeholder it generates a random key for
that process and logs a warning. Sessions then do not survive a restart, which
is a visible nuisance in development and precisely the kind that gets fixed — a
guessable key is invisible and gets deployed. Set a real one and it is used as
given.

`GET /api/admin/system` now reports `security.jwtSecretConfigured` so an admin
can see the state without reading logs.

---

## Tests

176 -> **182 passing, 0 failing.**

New section [36] asserts the shipped placeholder, the old code default and the
empty string are all recognised as public, that the active signing key is never
one of them, and that the generated fallback is long enough to resist guessing.

Sections [34] and [35] from V7.9.8 (mixed-format pagination, admin route
guards) are included.

---

## What is NOT verified

This was developed without torch installed, so nothing here exercised EasyOCR,
SBERT or Ollama against a real scan. Verified: the pagination logic, the PDF
geometry, the scoring path, the route guards, the secret handling, and a
successful `vite build` producing a valid manifest and service worker.

Run `python check_ai_services.py` after merging to confirm the four models
still load.

---

## Still open

* The QR code is drawn but never decoded. Page identity rests entirely on
  upload order, and the page-count check is the only thing between a misordered
  scan and a confidently wrong grade. This is the next thing worth doing.
* `OCR_DECODER=beamsearch` overflow on long lines.
* Offline upload queueing, as described above.
* An admin-editable branding page, if your panel expects to see one.
