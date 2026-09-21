import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BackButton, PageHeader, PageShell, StatusBadge } from "../../../components/prof/PageShell";
import { getSubmissionByStudent, getSubmissionFileUrl } from "../../../api/examsApi";

const initials = (name) => name.split(" ").map((n) => n[0]).slice(0, 2).join("").toUpperCase();

function fmtDate(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return value;
  }
}

function AnswerBadge({ q }) {
  if (q.isBlank) return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">Blank</span>;
  if (q.isAmbiguous) return <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-600">Ambiguous</span>;
  if (q.isCorrect) return <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-600">Correct</span>;
  return <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-bold text-rose-600">Incorrect</span>;
}

/* -------------------------------------------------------------------------
 * Scanned pages
 * ---------------------------------------------------------------------- */

/** Every scanned page of one submission, in the order they were printed.
 *
 * Pages are fetched lazily — a submission can run to many essay pages and
 * there is no reason to pull all of them for a professor who only glances at
 * the first. Each blob URL is revoked when the viewer unmounts.
 */
function ScanViewer({ submissionId, files }) {
  const pages = useMemo(() => {
    const list = [];
    // A path can legitimately appear in both slots when the same photo was
    // uploaded twice. Showing it as two pages makes the pager look broken --
    // the counter advances but the picture does not -- so identical paths are
    // collapsed and the duplication is reported instead.
    const seen = new Set();
    const add = (path, page) => {
      if (!path || seen.has(path)) return;
      seen.add(path);
      list.push(page);
    };

    add(files?.page1, {
      which: "page1",
      index: 0,
      label: "Page 1",
      caption: "Multiple-choice sheet used for OMR bubble detection.",
    });
    (files?.essayPages || []).forEach((path, i) => {
      add(path, {
        which: "essay",
        index: i,
        label: `Essay page ${i + 1}`,
        caption: "Handwritten answer area read by the OCR engine.",
      });
    });
    return list;
  }, [files]);

  const duplicateCount =
    (files?.page1 ? 1 : 0) + (files?.essayPages || []).filter(Boolean).length - pages.length;

  const [active, setActive] = useState(0);
  const [zoomed, setZoomed] = useState(false);
  const [urls, setUrls] = useState({});
  const [errors, setErrors] = useState({});
  const cache = useRef({});

  useEffect(() => {
    const store = cache.current;
    return () => {
      Object.values(store).forEach((url) => URL.revokeObjectURL(url));
      cache.current = {};
    };
  }, [submissionId]);

  const load = useCallback(
    (page) => {
      if (!submissionId || !page) return;
      const key = `${page.which}:${page.index}`;
      if (cache.current[key] || errors[key]) return;
      getSubmissionFileUrl(submissionId, page.which, page.index)
        .then((url) => {
          cache.current[key] = url;
          setUrls((prev) => ({ ...prev, [key]: url }));
        })
        .catch((err) => {
          setErrors((prev) => ({ ...prev, [key]: err.message || "That page could not be loaded." }));
        });
    },
    [submissionId, errors]
  );

  // Load the visible page and quietly pre-fetch its neighbour, so paging
  // through a booklet does not flash a spinner on every click.
  useEffect(() => {
    load(pages[active]);
    load(pages[active + 1]);
  }, [active, pages, load]);

  useEffect(() => {
    setActive((current) => Math.min(current, Math.max(0, pages.length - 1)));
  }, [pages.length]);

  // Escape closes the zoom overlay, and body scroll is locked while it is
  // open so a phone does not scroll the page behind the image.
  useEffect(() => {
    if (!zoomed) return undefined;
    const onKey = (e) => e.key === "Escape" && setZoomed(false);
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [zoomed]);

  if (pages.length === 0) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <h2 className="font-bold text-[#0B1739]">Scanned answer sheet</h2>
        <div className="mt-4 flex min-h-[220px] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-center text-slate-400 sm:min-h-[280px]">
          <div>
            <i className="bx bxs-image text-5xl" />
            <p className="mt-2 text-xs">No pages were uploaded for this submission.</p>
          </div>
        </div>
      </section>
    );
  }

  const page = pages[active];
  const key = `${page.which}:${page.index}`;
  const url = urls[key];
  const error = errors[key];
  const step = (delta) => setActive((i) => Math.min(pages.length - 1, Math.max(0, i + delta)));

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      {/* Title and pager share a row from sm up; on a phone the pager drops
          beneath the title so neither is squeezed to a few pixels. */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-[#0B1739] sm:text-base">
            {page.label} — Scanned answer sheet
          </h2>
          <p className="mt-0.5 text-xs leading-5 text-slate-500">{page.caption}</p>
        </div>
        {pages.length > 1 && (
          <div className="flex shrink-0 items-center gap-1 self-start">
            <button
              type="button"
              onClick={() => step(-1)}
              disabled={active === 0}
              aria-label="Previous page"
              className="grid h-10 w-10 place-items-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57] disabled:cursor-not-allowed disabled:opacity-30 sm:h-9 sm:w-9"
            >
              <i className="bx bx-chevron-left text-xl" />
            </button>
            <span className="min-w-[56px] text-center text-xs font-bold tabular-nums text-slate-500">
              {active + 1} / {pages.length}
            </span>
            <button
              type="button"
              onClick={() => step(1)}
              disabled={active === pages.length - 1}
              aria-label="Next page"
              className="grid h-10 w-10 place-items-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57] disabled:cursor-not-allowed disabled:opacity-30 sm:h-9 sm:w-9"
            >
              <i className="bx bx-chevron-right text-xl" />
            </button>
          </div>
        )}
      </div>

      {duplicateCount > 0 && (
        <div className="mb-3 flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-4 text-amber-800">
          <i className="bx bx-error-circle mt-px shrink-0" />
          <span>
            The same file was uploaded to more than one page slot, so this submission has fewer
            distinct pages than expected. Re-scan the student with each page in its own slot.
          </span>
        </div>
      )}

      {/* Height is viewport-relative on a phone. A fixed 520px frame is taller
          than a small screen, which pushes the score breakdown entirely below
          the fold and makes the page feel like it is only an image. */}
      <div className="flex min-h-[220px] items-center justify-center overflow-hidden rounded-xl border border-dashed border-slate-300 bg-slate-50 sm:min-h-[280px]">
        {url ? (
          <button
            type="button"
            onClick={() => setZoomed(true)}
            className="group relative w-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57]"
            aria-label={`View ${page.label} full size`}
          >
            <img
              src={url}
              alt={`${page.label} scan`}
              className="mx-auto max-h-[48vh] w-auto max-w-full object-contain sm:max-h-[520px]"
            />
            <span className="pointer-events-none absolute bottom-2 right-2 rounded-full bg-black/55 px-2.5 py-1 text-[10px] font-bold text-white opacity-80 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100">
              <i className="bx bx-expand-alt mr-1" />
              Tap to enlarge
            </span>
          </button>
        ) : (
          <div className="px-4 py-10 text-center text-slate-400">
            <i className={`bx ${error ? "bx-error-circle" : "bxs-image"} text-5xl`} />
            <p className="mt-2 text-xs">{error || "Loading scanned page…"}</p>
          </div>
        )}
      </div>

      {pages.length > 1 && (
        <div className="-mx-1 mt-3 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {pages.map((p, i) => (
            <button
              key={`${p.which}:${p.index}`}
              type="button"
              onClick={() => setActive(i)}
              aria-current={i === active}
              className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-[11px] font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57] ${
                i === active ? "bg-[#291C57] text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {zoomed && url && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-3"
          onClick={() => setZoomed(false)}
          role="dialog"
          aria-modal="true"
          aria-label={`${page.label}, full size`}
        >
          <img src={url} alt={`${page.label} scan, full size`} className="max-h-full max-w-full object-contain" />
          <button
            type="button"
            onClick={() => setZoomed(false)}
            aria-label="Close"
            className="absolute right-3 top-3 grid h-11 w-11 place-items-center rounded-full bg-white/15 text-white backdrop-blur hover:bg-white/25"
          >
            <i className="bx bx-x text-3xl" />
          </button>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Essay grading breakdown
 * ---------------------------------------------------------------------- */

/** Read-only rubric breakdown for one essay answer.
 *
 * Contributions are percentage points and sum to the answer's percentage, so
 * this table is the actual arithmetic behind the score rather than a summary
 * of it. Criteria the engine could not evaluate are listed separately, since a
 * missing criterion is redistributed across the others rather than scored
 * zero — showing it as an empty bar would misrepresent the result.
 */
function CriteriaTable({ criteria, rubric }) {
  const counted = (criteria || []).filter((c) => c.counted !== false);
  const skipped = (criteria || []).filter((c) => c.counted === false);
  const total = counted.reduce((sum, c) => sum + (Number(c.contribution) || 0), 0);

  const sourceLabel =
    {
      question: "This question's rubric",
      exam_legacy: "Exam-level rubric (legacy)",
      system_default: "System default rubric",
    }[rubric?.source] || "Configured rubric";

  if (counted.length === 0 && skipped.length === 0) {
    return <p className="text-xs text-slate-400">No rubric breakdown was recorded for this answer.</p>;
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px]">
        <span className="font-bold uppercase tracking-wide text-slate-400">{sourceLabel}</span>
        <span className="font-bold text-slate-400">Weight · Score · Contribution</span>
      </div>

      <div className="space-y-3">
        {counted.map((c) => (
          <div key={c.key || c.label}>
            {/* On a phone the three numbers go under the label instead of
                competing with it for one line, which is what forced the
                criterion name to truncate to a couple of words. */}
            <div className="mb-1.5 flex flex-col gap-0.5 text-xs sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <span className="min-w-0 font-semibold text-slate-600 sm:truncate">
                {c.label || c.name}
                {c.detail?.pending && (
                  <span className="ml-1.5 rounded-full bg-amber-50 px-1.5 py-0.5 text-[9px] font-bold text-amber-700">
                    fallback
                  </span>
                )}
              </span>
              <span className="shrink-0 font-bold tabular-nums text-slate-400">
                {Math.round(c.configuredWeight ?? (c.weight || 0) * 100)}%
                <span className="mx-1 text-slate-300">·</span>
                {Math.round((c.value || 0) * 100)}%
                <span className="mx-1 text-slate-300">·</span>
                <span className="text-[#291C57]">{Number(c.contribution || 0).toFixed(1)}%</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.round((c.value || 0) * 100)}%`, backgroundColor: c.color || "#5B8DEF" }}
              />
            </div>
            {c.implementation && (
              <p className="mt-1 text-[10px] leading-4 text-slate-400">{c.implementation}</p>
            )}
          </div>
        ))}
      </div>

      {counted.length > 0 && (
        <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5 text-xs">
          <span className="font-bold text-slate-600">Total</span>
          <span className="font-extrabold tabular-nums text-[#291C57]">{total.toFixed(1)}%</span>
        </div>
      )}

      {skipped.length > 0 && (
        <div className="mt-3 space-y-1.5 rounded-lg bg-amber-50 px-3 py-2.5">
          <p className="text-[11px] font-bold text-amber-900">
            <i className="bx bx-error-circle mr-1" />
            Some configured criteria could not be graded
          </p>
          {skipped.map((c) => (
            <p key={c.key || c.label} className="text-[11px] leading-4 text-amber-800">
              {c.unavailableReason || `${c.label || c.name} could not be evaluated.`}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function EssayBreakdownCard({ q, answerNumber, onGrade }) {
  const [showText, setShowText] = useState(false);
  const score = q.score ?? q.autoScore;
  const transcript = (q.answerText || "").trim();

  return (
    <div className="rounded-xl border border-slate-200 p-3.5 sm:p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* The printed sheet numbers essays 1..n on their own, while
              questionNumber counts every question in the exam -- with one MCQ
              first, the only essay is question 2 but is printed as
              "[ Answer 1 ]". Match the paper the professor is holding. */}
          <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">
            Answer {answerNumber}
            <span className="ml-1.5 font-semibold normal-case tracking-normal text-slate-300">
              Question {q.questionNumber}
            </span>
          </p>
          <p className="mt-0.5 line-clamp-2 text-sm font-semibold leading-5 text-slate-700">
            {q.questionText}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-lg font-extrabold tabular-nums leading-tight text-[#291C57]">
            {score !== null && score !== undefined ? score : "—"}
            <span className="text-sm font-bold text-slate-400">/{q.points}</span>
          </p>
          {q.isOverridden ? (
            <p className="text-[10px] font-bold leading-tight text-amber-600">
              Adjusted from {q.autoScore ?? "—"}
            </p>
          ) : (
            <p className="text-[10px] font-semibold leading-tight text-slate-400">AI score</p>
          )}
        </div>
      </div>

      {q.isBlank ? (
        <>
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">
            No text was read from this answer box. Check the scanned page above, then score it
            by hand if the student did write an answer.
          </p>
          {/* A blank transcription is exactly when a manual score matters most,
              so the override state stays visible here rather than being hidden
              behind the empty-answer message. */}
          {q.isOverridden ? (
            <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2">
              <p className="text-[11px] font-bold text-amber-900">
                Scored by hand: {q.score}/{q.points}
              </p>
              {q.overrideReason && (
                <p className="mt-0.5 text-[11px] leading-4 text-amber-800">{q.overrideReason}</p>
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={onGrade}
              className="mt-2 py-1 text-[11px] font-bold text-[#291C57] underline underline-offset-2 hover:text-[#211645] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57]"
            >
              Score this answer by hand
            </button>
          )}
        </>
      ) : (
        <>
          <CriteriaTable criteria={q.criteria} rubric={q.rubric} />

          {transcript && (
            <div className="mt-3 border-t border-slate-100 pt-3">
              <button
                type="button"
                onClick={() => setShowText((v) => !v)}
                aria-expanded={showText}
                className="flex items-center gap-1 py-1 text-[11px] font-bold text-slate-500 hover:text-[#291C57] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57]"
              >
                <i className={`bx ${showText ? "bx-chevron-up" : "bx-chevron-down"} text-base`} />
                {showText ? "Hide" : "Show"} what the OCR read
              </button>
              {showText && (
                <p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-50 px-3 py-2 text-xs leading-6 text-slate-600">
                  {transcript}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * MCQ breakdown
 * ---------------------------------------------------------------------- */

/** One question as a card, used on phones instead of the table.
 *
 * A five-column table cannot fit a phone without horizontal scrolling, and a
 * scroll container nested inside a vertically scrolling page is awkward to
 * operate with a thumb. The same data reads fine stacked.
 */
function McqCard({ q }) {
  return (
    <div className="flex items-center gap-3 border-b border-slate-100 py-2.5 last:border-0">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-50 text-xs font-bold text-slate-600">
        {q.questionNumber}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-sm text-slate-700">
          {q.selectedOption || "\u2014"}
          <span className="mx-1.5 text-slate-300">&rarr;</span>
          <span className="text-slate-500">{q.correctOption || "\u2014"}</span>
        </p>
        <p className="text-[10px] text-slate-400">
          selected &middot; correct &middot; {q.isCorrect ? q.points : 0}/{q.points} pts
        </p>
      </div>
      <AnswerBadge q={q} />
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Page
 * ---------------------------------------------------------------------- */

function ExamStudentSubmission() {
  const { classId, examId, studentId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getSubmissionByStudent(examId, studentId)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((err) => { if (!cancelled) setError(err.message || "Unable to load this submission."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [examId, studentId]);

  if (loading) {
    return <PageShell><div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading submission…</div></PageShell>;
  }

  if (error || !data) {
    return (
      <PageShell>
        <BackButton onClick={() => navigate(-1)} />
        <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">
          {error || "Submission not found."}
        </div>
      </PageShell>
    );
  }

  const { student, examTitle, status, submittedAt, finalScore, mcq, essay } = data;
  const processing = Boolean(data.processing);
  const failed = Boolean(data.failed);
  const hasMcqScore = mcq?.available && mcq?.score !== null && mcq?.score !== undefined;
  const released = Boolean(data.release?.released);
  const essayQuestions = essay?.questions || [];
  const goToGrading = () =>
    navigate(`/Professor/classes/${classId}/exams/${examId}/students/${studentId}/details`);
  const overriddenCount = essayQuestions.filter((q) => q.isOverridden).length;

  return (
    <PageShell>
      <BackButton onClick={() => navigate(-1)} />
      <PageHeader title={student.name} description={`${examTitle} · Student ID ${student.id}`} action={<StatusBadge status={status} />} />

      {processing && (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <i className="bx bx-loader-alt bx-spin mt-0.5 shrink-0" />
          <span>This answer sheet is still being scanned and graded in the background. Scores and the essay breakdown will appear here once it finishes — reload this page in a moment.</span>
        </div>
      )}
      {failed && (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <i className="bx bx-error-circle mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="font-bold">Processing failed for this submission</p>
            {data.error && <p className="mt-0.5 break-words text-xs text-rose-600">{data.error}</p>}
            <p className="mt-1 text-xs">Re-scan this student's sheet from the Upload page to try again.</p>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:gap-5 xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4 sm:space-y-5">
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center gap-3 bg-[#291C57] px-4 py-4 text-white sm:gap-4 sm:px-6 sm:py-5">
              <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-white/15 text-sm font-bold ring-1 ring-white/15 sm:h-14 sm:w-14">
                {initials(student.name)}
              </div>
              <div className="min-w-0">
                <h2 className="truncate text-base font-bold sm:text-lg">{student.name}</h2>
                <p className="mt-0.5 truncate text-xs text-white/70 sm:mt-1 sm:text-sm">
                  Submitted {fmtDate(submittedAt)}
                </p>
              </div>
            </div>

            {/* 2x2 on a phone with dividers in both directions, so the four
                figures read as a grid rather than four loose numbers. */}
            <div className="grid grid-cols-2 divide-x divide-y divide-slate-100 sm:grid-cols-4 sm:divide-y-0">
              <div className="px-3 py-3.5 text-center sm:px-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">MCQ Score</p>
                <p className="mt-1 text-lg font-extrabold text-[#291C57] sm:text-xl">
                  {hasMcqScore ? `${mcq.score}/${mcq.maxScore}` : mcq?.available ? "Not scanned" : "N/A"}
                </p>
              </div>
              <div className="px-3 py-3.5 text-center sm:px-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Essay Score</p>
                <p className="mt-1 text-lg font-extrabold text-[#291C57] sm:text-xl">
                  {essay?.available ? `${essay.score ?? "—"}/${essay.maxScore ?? "—"}` : "N/A"}
                </p>
              </div>
              <div className="px-3 py-3.5 text-center sm:px-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Final Score</p>
                <p className="mt-1 text-lg font-extrabold text-emerald-600 sm:text-xl">
                  {finalScore !== null && finalScore !== undefined ? `${finalScore}${data.maxScore ? `/${data.maxScore}` : ""}` : "Pending"}
                </p>
              </div>
              <div className="px-3 py-3.5 text-center sm:px-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Student sees</p>
                <p className={`mt-1 text-sm font-bold sm:text-base ${released ? "text-emerald-600" : "text-slate-500"}`}>
                  {released ? "Released" : "Hidden"}
                </p>
              </div>
            </div>
          </section>

          <ScanViewer submissionId={data.submissionId} files={data.files} />

          {essay?.available && essayQuestions.length > 0 && (
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
              <div className="mb-4">
                <h2 className="text-sm font-bold text-[#0B1739] sm:text-base">Essay score breakdown</h2>
                <p className="text-xs text-slate-500">
                  How each criterion contributed to the score, from the spaCy NLP grader.
                </p>
              </div>
              <div className="space-y-3.5 sm:space-y-4">
                {essayQuestions.map((q, i) => (
                  <EssayBreakdownCard
                    key={q.questionId}
                    q={q}
                    answerNumber={i + 1}
                    onGrade={goToGrading}
                  />
                ))}
              </div>
            </section>
          )}

          {mcq?.available && (
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="text-sm font-bold text-[#0B1739] sm:text-base">MCQ answer breakdown</h2>
                  <p className="mt-0.5 text-xs text-slate-500">Detected from the OpenCV OMR pipeline.</p>
                </div>
                {!mcq.omrAvailable && (
                  <span className="shrink-0 rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-bold text-amber-600">
                    OMR engine unavailable
                  </span>
                )}
              </div>

              {/* Cards on a phone, table from sm up. */}
              <div className="sm:hidden">
                {mcq.questions.map((q) => (
                  <McqCard key={q.questionId} q={q} />
                ))}
              </div>

              <div className="hidden sm:block">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-[11px] font-bold uppercase tracking-wide text-slate-400">
                      <th className="py-2 pr-3">Q#</th>
                      <th className="py-2 pr-3">Selected</th>
                      <th className="py-2 pr-3">Correct</th>
                      <th className="py-2 pr-3">Points</th>
                      <th className="py-2">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mcq.questions.map((q) => (
                      <tr key={q.questionId} className="border-b border-slate-50 last:border-0">
                        <td className="py-2 pr-3 font-semibold text-slate-700">{q.questionNumber}</td>
                        <td className="py-2 pr-3 font-mono text-slate-600">{q.selectedOption || "—"}</td>
                        <td className="py-2 pr-3 font-mono text-slate-600">{q.correctOption || "—"}</td>
                        <td className="py-2 pr-3 text-slate-500">{q.isCorrect ? q.points : 0}/{q.points}</td>
                        <td className="py-2"><AnswerBadge q={q} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>

        <aside className="min-w-0 space-y-4 sm:space-y-5 xl:sticky xl:top-5 xl:self-start">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <h2 className="text-sm font-bold text-[#0B1739] sm:text-base">Processing status</h2>
            <div className="mt-4 space-y-3">
              <div className="flex items-start gap-3">
                <i className="bx bxs-check-circle mt-px text-lg text-emerald-500" />
                <span className="text-sm leading-5 text-slate-600">Image uploaded</span>
              </div>
              <div className="flex items-start gap-3">
                <i className={`bx bxs-check-circle mt-px text-lg ${mcq?.available ? "text-emerald-500" : "text-slate-300"}`} />
                <span className="text-sm leading-5 text-slate-600">{mcq?.available ? `MCQ scored (${mcq.omrAvailable ? "OpenCV OMR" : "OMR unavailable"})` : "No MCQ portion"}</span>
              </div>
              <div className="flex items-start gap-3">
                <i className={`bx bxs-check-circle mt-px text-lg ${essay?.available && essay?.combinedText ? "text-emerald-500" : "text-slate-300"}`} />
                <span className="text-sm leading-5 text-slate-600">{essay?.available ? "Essay OCR completed" : "No essay portion"}</span>
              </div>
              <div className="flex items-start gap-3">
                <i className={`bx bxs-check-circle mt-px text-lg ${essay?.available && essay?.score !== null && essay?.score !== undefined ? "text-emerald-500" : "text-slate-300"}`} />
                <span className="text-sm leading-5 text-slate-600">
                  {essay?.available
                    ? `Essay graded (spaCy NLP)${overriddenCount ? ` · ${overriddenCount} manually adjusted` : ""}`
                    : "No essay grading needed"}
                </span>
              </div>
              <div className="flex items-start gap-3">
                <i className={`bx ${released ? "bxs-check-circle text-emerald-500" : "bx-hide text-slate-300"} mt-px text-lg`} />
                <span className="text-sm leading-5 text-slate-600">
                  {released ? "Score released to the student" : "Score not released to the student"}
                </span>
              </div>
            </div>
          </section>

          <div>
            <button
              onClick={goToGrading}
              disabled={processing || failed}
              className="w-full rounded-xl bg-[#291C57] px-4 py-3.5 text-sm font-bold text-white shadow-sm hover:bg-[#211645] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#291C57] disabled:cursor-not-allowed disabled:opacity-40 sm:py-3"
            >
              {essay?.available ? "Grade essays & release score" : "Review & release score"}
              <i className="bx bx-right-arrow-alt ml-1" />
            </button>
            <p className="mt-2 text-center text-[11px] leading-5 text-slate-400">
            {processing
              ? "Available once grading finishes."
              : failed
              ? "Re-scan this sheet before it can be graded."
              : essay?.available
              ? "Adjust individual essay scores, then release the result to the student."
                : "Release the result so the student can see their score."}
            </p>
          </div>
        </aside>
      </div>
    </PageShell>
  );
}

export default ExamStudentSubmission;