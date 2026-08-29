import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BackButton, PageHeader, PageShell } from "../../../components/prof/PageShell";
import {
  getSubmissionByStudent,
  overrideEssayScore,
  releaseStudentScore,
} from "../../../api/examsApi";

/** Render the answer with concept/keyword matches underlined.
 *
 * Offsets come from the backend so the highlighting matches exactly what the
 * grader scored, instead of the UI re-running its own text search and
 * potentially disagreeing with the marks it is illustrating.
 */
function HighlightedAnswer({ text, highlights }) {
  if (!text) {
    return <p className="text-sm italic text-slate-400">No answer text was detected for this question.</p>;
  }
  if (!highlights?.length) {
    return <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{text}</p>;
  }

  const parts = [];
  let cursor = 0;
  highlights.forEach((h, i) => {
    if (h.start > cursor) parts.push(text.slice(cursor, h.start));
    parts.push(
      <span
        key={i}
        className="rounded bg-slate-50 px-0.5 underline decoration-2"
        style={{ textDecorationColor: h.color }}
        title={h.reason}
      >
        {text.slice(h.start, h.end)}
      </span>
    );
    cursor = h.end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));

  return <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{parts}</p>;
}

/** The rubric table.
 *
 * Shows the weight the engine actually used, the criterion's own score, and
 * the resulting contribution in percentage points. The contributions sum to
 * the final percentage, so what the professor reads here is exactly the
 * arithmetic that produced the score.
 */
function CriteriaBars({ criteria, rubric }) {
  const counted = (criteria || []).filter((c) => c.counted !== false);
  const skipped = (criteria || []).filter((c) => c.counted === false);
  const totalContribution = counted.reduce((sum, c) => sum + (Number(c.contribution) || 0), 0);

  const sourceLabel = {
    question: "This question's rubric",
    exam_legacy: "Exam-level rubric (legacy)",
    system_default: "System default rubric",
  }[rubric?.source] || "Configured rubric";

  return (
    <div>
      <div className="mb-3 flex items-center justify-between text-[11px]">
        <span className="font-bold uppercase tracking-wide text-slate-400">{sourceLabel}</span>
        <span className="font-bold text-slate-400">Weight · Score · Contribution</span>
      </div>

      <div className="space-y-3">
        {counted.map((c) => (
          <div key={c.key || c.label}>
            <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
              <span className="min-w-0 truncate font-semibold text-slate-600">
                {c.label}
                {c.detail?.pending && (
                  <span className="ml-1.5 rounded-full bg-amber-50 px-1.5 py-0.5 text-[9px] font-bold text-amber-700">
                    fallback
                  </span>
                )}
              </span>
              <span className="shrink-0 font-bold text-slate-400">
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
                style={{ width: `${Math.round((c.value || 0) * 100)}%`, backgroundColor: c.color }}
              />
            </div>
            {c.implementation && (
              <p className="mt-1 text-[10px] text-slate-400">{c.implementation}</p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5 text-xs">
        <span className="font-bold text-slate-600">Total</span>
        <span className="font-extrabold text-[#291C57]">{totalContribution.toFixed(1)}%</span>
      </div>

      {skipped.length > 0 && (
        <div className="mt-3 space-y-1.5 rounded-lg bg-amber-50 px-3 py-2.5">
          <p className="text-[11px] font-bold text-amber-900">
            <i className="bx bx-error-circle mr-1" />
            Some configured criteria could not be graded
          </p>
          {skipped.map((c) => (
            <p key={c.key || c.label} className="text-[11px] leading-4 text-amber-800">
              {c.unavailableReason || `${c.label} could not be evaluated.`}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function EssayGradingCard({ q, examId, studentId, onScoreChanged }) {
  // `draft` is the value in the input; it only becomes an override when the
  // professor saves, so typing does not repeatedly hit the API.
  const [draft, setDraft] = useState(q.score ?? q.autoScore ?? 0);
  const [reason, setReason] = useState(q.overrideReason || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(q.score ?? q.autoScore ?? 0);
    setReason(q.overrideReason || "");
  }, [q.score, q.autoScore, q.overrideReason]);

  const max = q.points || 0;
  const clamp = (v) => Math.min(max, Math.max(0, Number.isFinite(v) ? v : 0));
  const dirty = Number(draft) !== Number(q.score ?? q.autoScore ?? 0) || reason !== (q.overrideReason || "");

  const save = async (clear = false) => {
    setSaving(true); setError(""); setSaved(false);
    try {
      const result = await overrideEssayScore(examId, studentId, q.questionId, {
        score: clear ? null : clamp(Number(draft)),
        reason: clear ? null : reason,
      });
      setSaved(true);
      onScoreChanged(result);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e.message || "Unable to save the score.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Question {q.questionNumber}</p>
          <p className="mt-1 text-sm font-bold text-[#0B1739]">{q.questionText}</p>
        </div>
        {q.isOverridden && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#F1EFF7] px-2.5 py-1 text-[10px] font-bold text-[#291C57]">
            <i className="bx bx-user-check" /> Manually adjusted
          </span>
        )}
      </div>

      {q.summary && <p className="mt-2 text-xs text-slate-500">{q.summary}</p>}

      <div className="mt-4">
        <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-400">Extracted answer</p>
        <div className="rounded-xl bg-slate-50 px-3.5 py-3">
          <HighlightedAnswer text={q.answerText} highlights={q.highlights} />
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div>
          <p className="mb-3 text-[11px] font-bold uppercase tracking-wide text-slate-400">Score breakdown</p>
          <CriteriaBars criteria={q.criteria} rubric={q.rubric} />
          {q.semanticPending ? (
            <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-800">
              <i className="bx bx-info-circle mr-1" />
              Answer Relevance used a lexical fallback, not Sentence-BERT.
              {q.engine?.sbert?.error ? ` Reason: ${q.engine.sbert.error}` : ""}
            </p>
          ) : q.engine?.similarity === "sentence_transformer" ? (
            <p className="mt-3 text-[11px] leading-5 text-slate-400">
              Answer Relevance graded by Sentence-BERT
              {q.engine?.sbert?.model ? ` (${q.engine.sbert.model})` : ""}.
            </p>
          ) : null}
          {q.expectedResponseFormat && (
            <p className="mt-1 text-[11px] text-slate-400">
              Expected response format: {String(q.expectedResponseFormat).replace(/_/g, " ")}.
            </p>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
          <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">AI score</p>
          <p className="mt-0.5 text-sm font-bold text-slate-600">
            {q.autoScore ?? "—"}<span className="font-semibold text-slate-400">/{max}</span>
          </p>

          <p className="mt-3 text-[10px] font-bold uppercase tracking-wide text-slate-400">Override score</p>
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setDraft((s) => clamp(Number(s) - 1))}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            >
              <i className="bx bx-minus" />
            </button>
            <input
              type="number"
              min="0"
              max={max}
              step="0.5"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => setDraft(clamp(Number(draft)))}
              className="h-9 w-full min-w-0 rounded-lg border border-slate-200 bg-white text-center text-sm font-bold text-[#291C57] outline-none focus:border-[#291C57] focus:ring-4 focus:ring-[#291C57]/10"
            />
            <button
              type="button"
              onClick={() => setDraft((s) => clamp(Number(s) + 1))}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            >
              <i className="bx bx-plus" />
            </button>
          </div>
          <p className="mt-1 text-center text-[10px] text-slate-400">out of {max}</p>

          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)"
            className="mt-2.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-[#291C57] focus:ring-4 focus:ring-[#291C57]/10"
          />

          <button
            onClick={() => save(false)}
            disabled={saving || !dirty}
            className="mt-2.5 w-full rounded-lg bg-[#291C57] py-2.5 text-xs font-bold text-white disabled:opacity-40"
          >
            {saving ? "Saving..." : saved ? "Saved" : "Save override"}
          </button>

          {q.isOverridden && (
            <button
              onClick={() => save(true)}
              disabled={saving}
              className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white py-2 text-[11px] font-bold text-slate-500 hover:bg-slate-50 disabled:opacity-40"
            >
              Revert to AI score
            </button>
          )}

          {error && <p className="mt-2 text-[11px] text-rose-600">{error}</p>}
        </div>
      </div>
    </section>
  );
}

export default function ExamSubmissionDetails() {
  const { classId, examId, studentId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [releasing, setReleasing] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    getSubmissionByStudent(examId, studentId)
      .then(setData)
      .catch((e) => setError(e.message || "Unable to load this submission."))
      .finally(() => setLoading(false));
  }, [examId, studentId]);

  useEffect(load, [load]);

  const essayQuestions = data?.essay?.questions || [];

  const totals = useMemo(() => ({
    final: data?.finalScore,
    max: data?.maxScore,
    mcq: data?.mcq?.score,
    mcqMax: data?.mcq?.maxScore,
    essay: data?.essay?.score,
    essayMax: data?.essay?.maxScore,
  }), [data]);

  // After an override the server returns the recomputed totals, so the header
  // updates without a full refetch.
  const handleScoreChanged = (result) => {
    setData((prev) => prev && ({
      ...prev,
      finalScore: result.finalScore,
      maxScore: result.maxTotal ?? prev.maxScore,
      essay: {
        ...prev.essay,
        score: result.essayScore,
        questions: prev.essay.questions.map((q) =>
          q.questionId === result.questionId
            ? { ...q, score: result.score, overrideScore: result.overrideScore, isOverridden: result.isOverridden }
            : q
        ),
      },
    }));
  };

  const toggleRelease = async () => {
    const next = !data.release?.released;
    if (next) {
      const ok = window.confirm(
        `Release this score to ${data.student.name}?\n\nThey will immediately be able to see their final score, their answers and the answer key.`
      );
      if (!ok) return;
    }
    setReleasing(true); setNotice(""); setError("");
    try {
      const result = await releaseStudentScore(examId, studentId, next);
      setData((prev) => prev && ({
        ...prev,
        status: result.status,
        release: { ...prev.release, released: result.released, releasedAt: result.releasedAt },
      }));
      setNotice(next ? "Score released. The student can now see it." : "Score hidden from the student.");
    } catch (e) {
      setError(e.message || "Unable to change the release state.");
    } finally {
      setReleasing(false);
    }
  };

  if (loading) {
    return <PageShell><div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading grading details…</div></PageShell>;
  }

  if (error && !data) {
    return (
      <PageShell>
        <BackButton onClick={() => navigate(-1)} />
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700">{error}</div>
      </PageShell>
    );
  }

  if (data.processing || data.failed) {
    return (
      <PageShell>
        <BackButton onClick={() => navigate(`/Professor/classes/${classId}/exams/${examId}/students/${studentId}`)} />
        <PageHeader title="Grading Details" description={`${data.student.name} · ${data.examTitle}`} />
        <div className={`max-w-2xl rounded-2xl border p-6 text-center shadow-sm ${data.failed ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-white"}`}>
          <span className={`mx-auto grid h-14 w-14 place-items-center rounded-2xl text-3xl ${data.failed ? "bg-rose-100 text-rose-600" : "bg-amber-50 text-amber-600"}`}>
            <i className={`bx ${data.failed ? "bx-error-circle" : "bx-loader-alt bx-spin"}`} />
          </span>
          <h2 className="mt-4 text-base font-bold text-[#0B1739]">
            {data.failed ? "Processing failed for this submission" : "Still grading this submission"}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
            {data.failed
              ? (data.error || "Something went wrong while grading this answer sheet.")
              : "OCR, OMR and essay grading are running in the background. This page will have a full breakdown once that finishes — reload in a moment."}
          </p>
          {data.failed && (
            <button
              onClick={() => navigate(`/Professor/upload`)}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white"
            >
              <i className="bx bx-scan" /> Re-scan this student's sheet
            </button>
          )}
        </div>
      </PageShell>
    );
  }

  const released = Boolean(data.release?.released);

  return (
    <PageShell>
      <BackButton onClick={() => navigate(`/Professor/classes/${classId}/exams/${examId}/students/${studentId}`)} />
      <PageHeader
        title="Grading Details"
        description={`${data.student.name} · ${data.examTitle}`}
        action={
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-bold ring-1 ${released ? "bg-emerald-50 text-emerald-700 ring-emerald-100" : "bg-slate-100 text-slate-600 ring-slate-200"}`}>
              <i className={`bx ${released ? "bxs-check-circle" : "bx-hide"}`} />
              {released ? "Released to student" : "Not released"}
            </span>
          </div>
        }
      />

      {error && <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
      {notice && <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{notice}</div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_360px]">
        <div className="space-y-5">
          {essayQuestions.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center text-sm text-slate-500">
              This examination has no essay questions to grade.
            </div>
          ) : (
            essayQuestions.map((q) => (
              <EssayGradingCard
                key={q.questionId}
                q={q}
                examId={examId}
                studentId={studentId}
                onScoreChanged={handleScoreChanged}
              />
            ))
          )}
        </div>

        <aside className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Final score</p>
            <p className="mt-1 text-3xl font-extrabold text-[#291C57]">
              {totals.final ?? "—"}
              <span className="text-base font-semibold text-slate-400">/{totals.max ?? "—"}</span>
            </p>

            <div className="mt-4 space-y-2">
              {data.mcq?.available && (
                <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                  <span className="text-slate-500">Multiple choice</span>
                  <span className="font-bold text-slate-700">{totals.mcq ?? "—"}/{totals.mcqMax ?? "—"}</span>
                </div>
              )}
              {data.essay?.available && (
                <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                  <span className="text-slate-500">Essay</span>
                  <span className="font-bold text-slate-700">{totals.essay ?? "—"}/{totals.essayMax ?? "—"}</span>
                </div>
              )}
            </div>

            <button
              onClick={toggleRelease}
              disabled={releasing || (!released && (totals.final === null || totals.final === undefined))}
              className={`mt-5 w-full rounded-xl py-3 text-sm font-bold shadow-sm disabled:opacity-40 ${released ? "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50" : "bg-[#291C57] text-white hover:bg-[#211645]"}`}
            >
              {releasing ? "Working…" : released ? (<><i className="bx bx-hide mr-1" />Hide score from student</>) : (<><i className="bx bx-check mr-1" />Release score to student</>)}
            </button>

            <p className="mt-2 text-[11px] leading-5 text-slate-400">
              {released
                ? `Released${data.release?.releasedAt ? ` on ${new Date(data.release.releasedAt).toLocaleString()}` : ""}. Hiding it again removes the score from the student's view.`
                : "The student cannot see any score, answer or answer key until you release it."}
            </p>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <h2 className="text-sm font-bold text-[#0B1739]">Overrides</h2>
            <p className="mt-1 text-xs text-slate-500">
              An override replaces the AI score for one answer. The original AI score is kept, so you can revert at
              any time.
            </p>
            <div className="mt-3 space-y-1.5">
              {essayQuestions.map((q) => (
                <div key={q.questionId} className="flex items-center justify-between text-xs">
                  <span className="text-slate-500">Question {q.questionNumber}</span>
                  <span className={`font-bold ${q.isOverridden ? "text-[#291C57]" : "text-slate-400"}`}>
                    {q.isOverridden ? `${q.overrideScore}/${q.points} (adjusted)` : `${q.autoScore ?? "—"}/${q.points}`}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </PageShell>
  );
}
