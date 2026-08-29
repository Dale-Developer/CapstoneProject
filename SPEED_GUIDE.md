# ESSCAN V7.9.5 — Everything That Affects Speed

You asked for a complete picture of what makes OCR extraction, Ollama
verification, and NLP grading fast or slow — not just what I already
changed. This covers both.

---

## Part 1 — What was actually wrong (found by reading the code, not guessed)

### "Confirm student" was slow
Every identification pass paid for three stacked costs on **every single
scan**, whether you needed them or not:

1. **Corner/registration-mark detection ran at full camera resolution**
   (often 3000-4000px on a modern phone) — even though only 4 corner
   *coordinates* were ever kept. The actual detected preview image was
   thrown away and re-warped from scratch at full resolution anyway. This
   was pure waste on every page, not just identification.
2. **EasyOCR multi-pass** on the header crop.
3. **Ollama fires whenever EasyOCR confidence dips below 0.62** — common
   for messy handwriting — and a 3B vision model on CPU is genuinely slow
   per call (multiple seconds).

None of this was a bug exactly — it was correct, just unnecessarily
expensive. Fixed below.

### Matching was inaccurate
This was the real finding: **Ollama never saw your class roster.** It did
blind, open-ended handwriting transcription — "read whatever you see" —
and a *separate* fuzzy-text step then tried to reconcile that guess against
your enrolled students. Any transcription slip on a name it's never seen
directly produced a wrong or low-confidence match. This wasn't a threshold
or fuzzy-matching-algorithm problem; the model was solving a harder problem
than it needed to.

### Grading throughput
Each essay question in a submission paid its own separate Sentence-BERT
forward pass. A submission with several essay questions did that many times
over for no benefit — SBERT's per-call overhead (tokenization, batch setup)
is largely fixed regardless of batch size.

---

## Part 2 — What I changed

### 1. Scanner detection now runs on a capped copy, not the full photo
`services/omr.py` — `_warp()` downscales to `SCANNER_DETECTION_MAX_DIM`
(default 1800px) purely for corner detection and orientation scoring, then
scales the winning corner coordinates back up to the original resolution
before the real perspective warp runs. **Final OCR/OMR image quality is
unchanged** — I traced every caller first to confirm nothing else depends
on the discarded low-resolution preview; the one hot-path consumer
(`scanner.prepare_scan()`) only ever used the corner coordinates.

**Please validate this before trusting it for a real batch.** I cannot test
this against a real scanned answer sheet in this environment. Scan a few
students first and confirm alignment succeeds and looks the same as before.
There's a hard constraint worth knowing: registration marks below ~50px (in
whatever resolution they're evaluated at) get rejected, so don't lower
`SCANNER_DETECTION_MAX_DIM` below what your camera's marks need without
checking. Set it to `0` to fully disable and restore the exact original
behavior if you see any alignment regressions.

### 2. Ollama identification is now roster-constrained
`services/ocr_hybrid.py` — when Ollama fires for identification, it's now
shown your actual class roster and asked to **pick the closest matching
name from it**, rather than transcribe blind. This fixes both problems at
once:
- **Accuracy**: closed-set matching against real candidates is a
  dramatically easier task for a vision model than open-ended handwriting
  transcription of a name it's never seen.
- **Speed**: copying a name it selects needs far fewer output tokens than
  spelling one out character by character. Identification-specific
  `num_predict` is now capped separately (`OLLAMA_ID_NUM_PREDICT=80`)
  instead of sharing the much higher essay-transcription default (512).

Falls back to the original open-ended prompt automatically if no roster is
available. Verified with 154 automated checks; **the actual OCR accuracy
improvement on your specific handwriting can only be judged by you scanning
real students** — I don't have real scanned sheets to test against.

### 3. Essay grading batches Sentence-BERT calls per submission
`services/nlp_spacy.py` (`batch_semantic_similarity`) and
`services/submission_pipeline.py` (`grade_essays`) — every essay question in
one submission is now encoded in a **single** SBERT call instead of one per
question. Verified byte-for-bit identical scores to the old one-at-a-time
path (a batching bug that silently shifted scores would be far worse than
one that crashed loudly, so this was tested directly, not just "doesn't
error").

### 4. Stale identification requests are now actually cancelled
`frontend/src/pages/Professor/Upload/index.jsx` — swapping to a new photo
before the previous one finished identifying used to let the old request
run to completion server-side and just discard the result. It's now
actually aborted via `AbortController`, freeing up EasyOCR/Ollama for the
photo you're actually waiting on. Found and fixed a related bug while
wiring this up: the shared API client was swallowing *all* fetch failures
— including deliberate cancellations — into a generic "can't connect to the
backend" error, which would have shown a false alarm on every routine
photo swap.

---

## Part 3 — Every other lever, and who controls each one

### Config you can tune right now (already in `.env`)

| Variable | Default | What it trades off |
|---|---|---|
| `SCANNER_DETECTION_MAX_DIM` | 1800 | Lower = faster detection, risk of missing small marks. `0` = original behavior. |
| `OLLAMA_ID_NUM_PREDICT` | 80 | Lower = faster identification, risk of a truncated name on unusually long names. |
| `OLLAMA_NUM_PREDICT` | 512 | Same trade-off, for essay-answer transcription specifically. |
| `OLLAMA_NUM_CTX` | 4096 | Larger = handles bigger prompts/images, slower. |
| `OLLAMA_OCR_MIN_CONFIDENCE` | 0.62 | Raise it → Ollama fires less often (faster, more EasyOCR-only reliance). Lower it → fires more often (slower, more verification). |
| `SBERT_BATCH_SIZE` | 32 | Raise on a GPU with headroom for more throughput per call. |
| `OLLAMA_KEEP_ALIVE` | 15m | Already set — keeps the model resident between calls so it isn't reloaded from disk each time. |
| `ESSCAN_PAGE_WORKERS` | tunable | How many answer-sheet pages process concurrently within one submission. |

### The one thing that would help more than everything above combined: a GPU

Every one of the code changes above squeezes waste out of a CPU-bound
pipeline. If the machine running this has an NVIDIA GPU, or you have access
to one (even a modest one, or a short-term cloud rental), switching to GPU
inference is typically a **5-20x** speedup for exactly the three things
you asked about:

- **EasyOCR**: set `EASYOCR_GPU=1` in `.env`.
- **Sentence-BERT**: set `SBERT_DEVICE=cuda` in `.env`.
- **Ollama**: uses GPU automatically if CUDA is available and the Ollama
  install supports it — no config change needed on your side, just the
  hardware/driver.

This is a hardware/deployment decision, not something I can turn on for you
from here — but if a GPU is available to you at all, it is the single
biggest lever on this list.

### The honest throughput ceiling for scanning 30+ students back-to-back

Background grading tasks (from the earlier async-processing work) run
concurrently as far as FastAPI is concerned, but EasyOCR recognition calls
are deliberately serialized behind a lock (its models are not documented as
thread-safe), and a single local Ollama instance can only truly process one
`generate()` call at a time regardless of how many requests are queued.

**This means total wall-clock time for grading 30 submissions is roughly
bounded by (per-sheet processing time) × 30, run essentially serially,
no matter how fast any single call is made.** The changes in this update
reduce the per-sheet multiplier significantly, but they don't remove the
serial bottleneck itself. Removing that bottleneck for real (true parallel
throughput, not just faster individual calls) would require one of:

- A GPU, which allows genuinely parallel/batched inference.
- Running a second Ollama instance on separate hardware and load-balancing
  between them (`OLLAMA_BASE_URL` can point anywhere reachable).
- A proper task-queue architecture (Celery/RQ + multiple worker processes),
  which is a real infrastructure change, not a tuning knob — reasonable for
  a production deployment, likely overkill for a capstone project.

I did not build this last one. Flagging it because "everything that can
speed this up" should include the honest ceiling, not just the levers
within easy reach.

---

## Verify

```powershell
cd backend
python tests_v7_9.py
```

**Expect: `PASSED: 154   FAILED: 0`** (152 with `SBERT_ENABLED=false` — two
SBERT-specific checks correctly skip).

New in this run: `[30]` proves batched and individual similarity scores are
identical; `[31]` confirms the roster reaches the identification pipeline.

**What the test suite cannot verify**: whether corner detection still
succeeds on your real answer sheets at the lower resolution, and whether
roster-constrained matching is actually more accurate on your students'
real handwriting. Both need a real scan to judge — please try a small batch
before trusting this for a full class.
