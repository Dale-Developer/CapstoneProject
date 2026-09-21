# ESSCAN V7.9.6 — OCR extraction fixes + submission UI

## Files

| File | Change |
|---|---|
| `backend/services/sheet_layout.py` | **NEW.** Single source of truth for answer-sheet geometry. |
| `backend/services/exam_pdf.py` | Answer boxes now stack instead of overlapping; geometry from `sheet_layout`. |
| `backend/services/ocr_hybrid.py` | Crop geometry from `sheet_layout`; recognition and arbitration fixes. |
| `backend/services/submission_pipeline.py` | Passes `page_index` to the essay extractor. |
| `frontend/src/pages/Professor/Exams/ExamStudentSubmission.jsx` | Multi-page scan viewer + essay criteria breakdown. |

Install order is unchanged. No new dependencies, no migration.

## Backend changes

### 1. Shared geometry (`sheet_layout.py`)
The PDF generator and the OCR cropper each carried their own copy of the page
coordinates, and they had drifted. Both now import the same module, so a
change to the printed layout automatically moves the crop with it.

### 2. The first written line is no longer cut off
`crop_top` was `box_y + box_h - 46`. The first printed guide line is at
`box_y + box_h - 45` — one point higher. Handwriting sits *on* a line and
extends upward, so the whole first line fell outside the crop.

Measured on a 3x master page (1836x2808 px):

```
first guide line   525 px
OLD crop ceiling   528 px   -> line 1 lost
NEW crop ceiling   468 px   -> 57 px (19 pt) of headroom
```

`CROP_INSET_TOP` is now 26 pt: clear of the `[ Answer N ]` label baseline at
22 pt, well above the first line at 45 pt.

### 3. Answer boxes stack (PDF fix)
`_draw_essay_answer_page` ignored the loop index and drew every box at
`box_y = bottom, box_h = top - bottom`. Two essays on a page produced two
identical overlapping full-page rectangles, while the OCR split the page in
half. One continuous answer was sliced in two and filed under two questions.

**Sheets with two answers on a page must be reprinted.** Single-answer pages
are byte-identical to before (`essay_box(top, 1, 0)` returns the old values),
so already-printed single-answer sheets still scan correctly.

### 4. Per-page header height
`top` was chosen from exam-level `has_mcq` alone. Only the first physical
answer-sheet page carries the tall boxed ID field, so on an essay-only exam
page 2 onward was cropped 56 pt (about 3 lines) too low.
`essay_student_id_mode(has_mcq, page_index)` now decides per page.

### 5. Unaligned pages fall back to whole-page OCR
When `omr._warp()` failed, `prepare_scan` returned the raw phone photo and the
cropper applied fixed rectangles to it anyway, landing somewhere arbitrary and
returning a confident-looking empty answer. Unrectified pages are now read
whole and flagged `degraded: true` in the response.

### 6. Clustering no longer deletes text
`_cluster` merged on raw IoU >= 0.25 with no size guard. Each cluster yields
exactly one winner, so two genuinely different regions merged means one is
deleted. Guide lines are 20 pt apart and `add_margin` inflates every box by
10%, so vertically adjacent handwriting reached that bar easily.

Now: IoU >= 0.50 (`OCR_CLUSTER_IOU`) plus a 2.8x area-ratio guard
(`OCR_CLUSTER_MAX_AREA_RATIO`) — a word and a whole line are never competing
readings of the same thing.

### 7. The fallback pass is judged on coverage too
Acceptance compared length-weighted *mean* confidence, so a pass that
recovered extra words lowered the mean and was discarded — the fallback was
penalised for working. It now also wins on a 15% gain in transcribed
characters (`OCR_SECOND_PASS_TEXT_GAIN`).

### 8. Beam search and working resolution restored
`OCR_DECODER` defaults back to `beamsearch` (width 10), `OCR_CANVAS_SIZE` to
3200, `OCR_MAG_RATIO` to 1.25, `OCR_TARGET_WIDTH` to 2200. Greedy CTC commits
to the top character every frame, which is where most errors on joined-up
handwriting come from. These run on small crops, not full pages.

### 9. Ruled lines are filtered out
`_is_rule_artifact` drops detections with no alphanumeric content whose box is
12x wider than tall — the printed guide lines. Left in, each became its own
output line and pushed real handwriting apart during reconstruction.

### 10. The vision verifier can actually arbitrate
Verification ran below 0.62 but arbitration preferred EasyOCR down to 0.55, so
Ollama was woken, disagreed, and was overruled across most of the range where
it had been called. Both bars are now `OLLAMA_OCR_MIN_CONFIDENCE`. A length
tie-break (`OLLAMA_MIN_LENGTH_RATIO`) keeps a suspiciously short vision
reading from replacing a longer EasyOCR one.

### 11. Model preamble is stripped
`_clean_ollama_text` removes "Sure! Here is the handwritten text:", code
fences and wrapping quotes. That scaffolding was previously stored as the
student's answer and graded for relevance and grammar.

### 12. The ID crop excludes the QR code
The header crop was the top 27% of the page, which swept in the QR block, the
exam title and the page label. `id_field_crop_box` crops the ID box itself.

## Frontend changes

`ExamStudentSubmission.jsx`:

- **`ScanViewer`** replaces the single hardcoded Page 1 image. Shows page 1 and
  every essay page with prev/next arrows, an `n / total` counter and labelled
  jump buttons. Pages load lazily with the next one pre-fetched; blob URLs are
  revoked on unmount. Uses the existing `which=essay&index=N` endpoint — no
  backend change needed.
- **`EssayBreakdownCard` / `CriteriaTable`** render the per-criterion rubric
  breakdown already present in `essay.questions[].criteria`: weight, criterion
  score, contribution in percentage points, and a total that equals the
  arithmetic behind the score. Skipped criteria are listed with their
  redistribution reason rather than shown as zero bars. Each answer has a
  collapsible "what the OCR read" panel — the fastest way to tell a genuine
  low score from a transcription failure.

## Environment knobs added

```
OCR_CLUSTER_IOU=0.50
OCR_CLUSTER_MAX_AREA_RATIO=2.8
OCR_SECOND_PASS_TEXT_GAIN=1.15
OCR_RULE_ASPECT=12.0
OLLAMA_MIN_LENGTH_RATIO=0.5
```

Changed defaults: `OCR_DECODER` greedy -> beamsearch, `OCR_BEAM_WIDTH` 5 -> 10,
`OCR_CANVAS_SIZE` 2400 -> 3200, `OCR_MAG_RATIO` 1.15 -> 1.25,
`OCR_TARGET_WIDTH` 1800 -> 2200, `OCR_MAX_WIDTH` 2400 -> 3200,
`OCR_MAX_UPSCALE` 3.5 -> 4.0.

Items 8 and 6 trade CPU for accuracy. If a scan gets too slow, lower
`OCR_CANVAS_SIZE` first — it is the largest single cost.

## Not changed, deliberately

No spell-correction pass was reintroduced. The V1 SymSpell step is gone from
this build, and adding it back would silently repair the student's own
spelling mistakes — which `nlp_spacy` separately scores as a grading
criterion. Doing it properly means storing a raw transcript for the spelling
criterion and a corrected one for the semantic criteria. That is a schema
change and belongs in its own patch.
