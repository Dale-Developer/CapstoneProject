import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getStudentExam } from "../../api/studentApi";
import { PageHeader, PageShell, BackButton } from "../../components/prof/PageShell";

function SubmissionCard({ submission, onUpload, onViewScore }) {
  // Three distinct states, each with a different next action: nothing
  // submitted, submitted but not released, and released.
  if (!submission) {
    return (
      <div className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-slate-100 text-2xl text-slate-400">
              <i className="bx bx-file-blank" />
            </span>
            <div>
              <p className="text-sm font-bold text-[#0B1739]">No answer sheet submitted</p>
              <p className="mt-0.5 text-xs text-slate-500">Upload your sheet when you are ready. You can only submit once.</p>
            </div>
          </div>
          <button onClick={onUpload} className="inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white">
            <i className="bx bx-upload" /> Upload answer sheet
          </button>
        </div>
      </div>
    );
  }

  const released = submission.scoresReleased;
  const processing = submission.processing;
  const failed = submission.failed;

  const icon = failed ? "bx-error-circle" : processing ? "bx-time-five" : released ? "bx-award" : "bx-time-five";
  const iconClass = failed ? "bg-rose-50 text-rose-600" : processing ? "bg-amber-50 text-amber-600" : released ? "bg-emerald-50 text-emerald-600" : "bg-[#F1EFF7] text-[#291C57]";
  const title = failed
    ? "We couldn't process your answer sheet"
    : processing
    ? "Your answer sheet is being graded"
    : released
    ? "Your score has been released"
    : "Answer sheet submitted";
  const subtitle = failed
    ? "Ask your professor to re-scan it for you."
    : processing
    ? "Scanning and grading now — this page will update automatically."
    : !released
    ? "Waiting for your professor to release your score."
    : "";

  return (
    <div className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className={`grid h-11 w-11 place-items-center rounded-xl text-2xl ${iconClass}`}>
            <i className={`bx ${icon}`} />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-bold text-[#0B1739]">{title}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {submission.submittedAt ? `Submitted ${new Date(submission.submittedAt).toLocaleString()}` : "Submitted"}
              {subtitle && ` · ${subtitle}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {released && !processing && submission.finalScore !== null && submission.finalScore !== undefined && (
            <div className="text-right">
              <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Final score</p>
              <p className="text-xl font-extrabold text-[#291C57]">
                {submission.finalScore}
                {submission.maxScore ? <span className="text-sm font-semibold text-slate-400">/{submission.maxScore}</span> : null}
              </p>
            </div>
          )}
          {!failed && (
            <button
              onClick={onViewScore}
              className={`inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold ${released && !processing ? "bg-[#291C57] text-white" : "border border-slate-200 text-slate-600 hover:bg-slate-50"}`}
            >
              {released && !processing ? <><i className="bx bx-bar-chart-alt-2" /> View my score</> : "View status"}
            </button>
          )}
        </div>
      </div>

      {submission.locked && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <i className="bx bx-lock-alt mt-0.5" />
          This submission is final. If your scan needs to be redone, ask your professor to re-scan it.
        </p>
      )}
    </div>
  );
}

export default function StudentExamView() {
  const { classId, examId } = useParams();
  const navigate = useNavigate();
  const [exam, setExam] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getStudentExam(examId)
      .then(setExam)
      .catch((e) => setError(e.message || "Unable to load examination."))
      .finally(() => setLoading(false));
  }, [examId]);

  if (loading) {
    return <PageShell><div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading examination...</div></PageShell>;
  }
  if (error || !exam) {
    return <PageShell><div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{error || "Examination not found."}</div></PageShell>;
  }

  const submission = exam.submission;

  return (
    <PageShell>
      <BackButton onClick={() => navigate(`/student/class/${classId}`)} />
      <PageHeader
        title={exam.title}
        description={`${exam.subject}${exam.date ? ` · ${new Date(`${exam.date}T00:00:00`).toLocaleDateString()}` : ""}`}
        action={
          !submission?.locked && (
            <button
              onClick={() => navigate(`/student/class/${classId}/exam/${examId}/upload`)}
              className="inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white"
            >
              <i className="bx bx-upload" />Upload answer sheet
            </button>
          )
        }
      />

      <SubmissionCard
        submission={submission}
        onUpload={() => navigate(`/student/class/${classId}/exam/${examId}/upload`)}
        onViewScore={() => navigate(`/student/class/${classId}/exam/${examId}/result`)}
      />

      <div className="mb-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-sm font-semibold text-[#0B1739]">Examination information</p>
        <p className="mt-1 text-xs text-slate-500">
          {exam.totalItems} items{exam.totalPoints ? ` · ${exam.totalPoints} points` : ""} · Status: {submission?.status || "Not submitted"}
        </p>
      </div>

      <section className="space-y-4">
        {exam.questions.map((q) => (
          <article key={q.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-bold text-[#0B1739]">{q.number}. {q.question}</p>
              {q.points ? <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">{q.points} pt{q.points === 1 ? "" : "s"}</span> : null}
            </div>
            {q.type === "MCQ" && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {(q.options || []).map((opt, i) => (
                  <div key={i} className="rounded-xl bg-slate-50 px-3 py-2.5 text-sm text-slate-700">
                    <span className="mr-2 font-bold">{"ABCDE"[i]}.</span>{opt}
                  </div>
                ))}
              </div>
            )}
          </article>
        ))}
      </section>
    </PageShell>
  );
}
