import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getStudentResult } from "../../api/studentApi";
import { BackButton, PageHeader, PageShell } from "../../components/prof/PageShell";

function pct(score, max) {
  if (score === null || score === undefined || !max) return null;
  return Math.round((score / max) * 100);
}

function ScoreRing({ score, max }) {
  const percentage = pct(score, max) ?? 0;
  const circumference = 2 * Math.PI * 52;
  const offset = circumference - (percentage / 100) * circumference;
  // Colour is a quick readability cue, not a pass/fail judgement — grading
  // thresholds vary by school, so the bands are deliberately gentle.
  const color = percentage >= 75 ? "#16A34A" : percentage >= 50 ? "#F59E0B" : "#E11D48";

  return (
    <div className="relative grid h-40 w-40 shrink-0 place-items-center">
      <svg className="h-40 w-40 -rotate-90" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="52" fill="none" stroke="#EEF2F7" strokeWidth="12" />
        <circle
          cx="60" cy="60" r="52" fill="none" stroke={color} strokeWidth="12"
          strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute text-center">
        <p className="text-3xl font-extrabold text-[#0B1739]">{score ?? "—"}</p>
        <p className="text-xs font-semibold text-slate-400">out of {max ?? "—"}</p>
        <p className="mt-0.5 text-xs font-bold" style={{ color }}>{percentage}%</p>
      </div>
    </div>
  );
}

function McqRow({ q }) {
  const badge = q.isBlank
    ? { label: "Blank", cls: "bg-slate-100 text-slate-500" }
    : q.isAmbiguous
    ? { label: "Unclear mark", cls: "bg-amber-50 text-amber-600" }
    : q.isCorrect
    ? { label: "Correct", cls: "bg-emerald-50 text-emerald-600" }
    : { label: "Incorrect", cls: "bg-rose-50 text-rose-600" };

  return (
    <tr className="border-b border-slate-50 last:border-0">
      <td className="py-2 pr-3 font-semibold text-slate-700">{q.questionNumber}</td>
      <td className="py-2 pr-3 font-mono text-slate-600">{q.selectedOption || "—"}</td>
      <td className="py-2 pr-3 font-mono text-slate-600">{q.correctOption || "—"}</td>
      <td className="py-2 pr-3 text-slate-500">{q.earned}/{q.points}</td>
      <td className="py-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>{badge.label}</span>
      </td>
    </tr>
  );
}

function EssayCard({ q }) {
  const percentage = pct(q.earned, q.points);
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Question {q.questionNumber}</p>
          <p className="mt-1 text-sm font-bold text-[#0B1739]">{q.questionText}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-2xl font-extrabold text-[#291C57]">
            {q.earned ?? "—"}<span className="text-sm font-semibold text-slate-400">/{q.points}</span>
          </p>
          {percentage !== null && <p className="text-xs font-semibold text-slate-400">{percentage}%</p>}
        </div>
      </div>

      {q.wasAdjusted && (
        <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-[#F1EFF7] px-2.5 py-1 text-[11px] font-bold text-[#291C57]">
          <i className="bx bx-user-check" /> Reviewed and adjusted by your professor
        </p>
      )}

      {q.answerText && (
        <div className="mt-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Your answer as scanned</p>
          <p className="mt-1.5 whitespace-pre-wrap rounded-xl bg-slate-50 px-3.5 py-3 text-sm leading-6 text-slate-700">
            {q.answerText}
          </p>
        </div>
      )}

      {q.criteria?.length > 0 && (
        <div className="mt-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">How this was scored</p>
          <div className="mt-2.5 space-y-2.5">
            {q.criteria.map((c) => (
              <div key={c.label}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-600">{c.label}</span>
                  <span className="font-bold text-slate-400">{Math.round((c.value || 0) * 100)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full" style={{ width: `${Math.round((c.value || 0) * 100)}%`, backgroundColor: c.color }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

export default function StudentResult() {
  const { classId, examId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getStudentResult(examId)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((e) => { if (!cancelled) setError(e.message || "Unable to load your result."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [examId]);

  if (loading) {
    return <PageShell><div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading your result...</div></PageShell>;
  }

  if (error || !data) {
    return (
      <PageShell>
        <BackButton onClick={() => navigate(-1)} />
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700">{error || "Result not found."}</div>
      </PageShell>
    );
  }

  const back = () => navigate(`/student/class/${classId}/exam/${examId}`);

  // Not submitted, still processing, failed, or graded but not yet released.
  // Each is a distinct, normal state and gets its own explanation rather than
  // a generic spinner or an empty screen.
  if (!data.released) {
    const processing = data.submission?.processing;
    const failed = data.submission?.failed;
    const icon = failed ? "bx-error-circle" : processing ? "bx-loader-alt bx-spin" : data.submitted ? "bx-time-five" : "bx-file-blank";
    const iconClass = failed ? "bg-rose-50 text-rose-600" : processing ? "bg-amber-50 text-amber-600" : data.submitted ? "bg-[#F1EFF7] text-[#291C57]" : "bg-slate-100 text-slate-400";
    const title = failed
      ? "We couldn't process your answer sheet"
      : processing
      ? "Grading your answer sheet…"
      : data.submitted
      ? "Waiting for your professor to release your score"
      : "No answer sheet submitted yet";

    return (
      <PageShell>
        <BackButton onClick={back} />
        <PageHeader title={data.examTitle} description={data.subject} />
        <div className="max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
          <span className={`mx-auto grid h-14 w-14 place-items-center rounded-2xl text-3xl ${iconClass}`}>
            <i className={`bx ${icon}`} />
          </span>
          <h2 className="mt-4 text-base font-bold text-[#0B1739]">{title}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">{data.message}</p>
          {!data.submitted && (
            <button
              onClick={() => navigate(`/student/class/${classId}/exam/${examId}/upload`)}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white"
            >
              <i className="bx bx-upload" /> Upload answer sheet
            </button>
          )}
        </div>
      </PageShell>
    );
  }

  const { mcq, essay } = data;

  return (
    <PageShell>
      <BackButton onClick={back} />
      <PageHeader
        title={data.examTitle}
        description={`${data.subject}${data.releasedAt ? ` · Released ${new Date(data.releasedAt).toLocaleDateString()}` : ""}`}
      />

      <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center">
          <ScoreRing score={data.finalScore} max={data.maxScore} />
          <div className="w-full min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Your final score</p>
            <p className="mt-1 text-sm text-slate-600">
              This is the score your professor released for this examination.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {mcq?.available && (
                <div className="rounded-xl bg-slate-50 px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Multiple choice</p>
                  <p className="mt-1 text-lg font-extrabold text-[#291C57]">
                    {mcq.score ?? "—"}<span className="text-sm font-semibold text-slate-400">/{mcq.maxScore}</span>
                  </p>
                </div>
              )}
              {essay?.available && (
                <div className="rounded-xl bg-slate-50 px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Essay</p>
                  <p className="mt-1 text-lg font-extrabold text-[#291C57]">
                    {essay.score ?? "—"}<span className="text-sm font-semibold text-slate-400">/{essay.maxScore}</span>
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {essay?.available && essay.questions?.length > 0 && (
        <section className="mb-5">
          <h2 className="mb-3 text-sm font-bold text-[#0B1739]">Essay answers</h2>
          <div className="grid gap-4">
            {essay.questions.map((q) => <EssayCard key={q.questionId} q={q} />)}
          </div>
        </section>
      )}

      {mcq?.available && mcq.questions?.length > 0 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h2 className="font-bold text-[#0B1739]">Multiple-choice answers</h2>
          <p className="mt-0.5 text-xs text-slate-500">Your detected mark compared with the answer key.</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[420px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-[11px] font-bold uppercase tracking-wide text-slate-400">
                  <th className="py-2 pr-3">Q#</th>
                  <th className="py-2 pr-3">Your answer</th>
                  <th className="py-2 pr-3">Correct</th>
                  <th className="py-2 pr-3">Points</th>
                  <th className="py-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {mcq.questions.map((q) => <McqRow key={q.questionId} q={q} />)}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-400">
            If a mark was read as blank or unclear and you believe that is wrong, contact your professor — they can re-scan your sheet.
          </p>
        </section>
      )}
    </PageShell>
  );
}
