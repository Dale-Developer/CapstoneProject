import { useEffect, useState } from "react";
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

function ExamStudentSubmission() {
  const { classId, examId, studentId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [page1Url, setPage1Url] = useState(null);
  const [imgError, setImgError] = useState("");

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

  useEffect(() => {
    if (!data?.submissionId || !data?.files?.page1) return undefined;
    let cancelled = false;
    let objectUrl = null;
    setImgError("");
    getSubmissionFileUrl(data.submissionId, "page1")
      .then((url) => {
        if (cancelled) { URL.revokeObjectURL(url); return; }
        objectUrl = url;
        setPage1Url(url);
      })
      .catch((err) => { if (!cancelled) setImgError(err.message || "Unable to load the scanned page."); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [data?.submissionId, data?.files?.page1]);

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
  const overriddenCount = (essay?.questions || []).filter((q) => q.isOverridden).length;

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

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center gap-4 bg-[#291C57] px-5 py-5 text-white sm:px-6">
              <div className="grid h-14 w-14 shrink-0 place-items-center rounded-full bg-white/15 text-sm font-bold ring-1 ring-white/15">{initials(student.name)}</div>
              <div className="min-w-0"><h2 className="truncate text-lg font-bold">{student.name}</h2><p className="mt-1 text-sm text-white/70">Submitted {fmtDate(submittedAt)}</p></div>
            </div>
            <div className="grid grid-cols-2 divide-slate-100 px-4 py-4 sm:grid-cols-4 sm:divide-x sm:px-6">
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">MCQ Score</p>
                <p className="mt-1 text-xl font-extrabold text-[#291C57]">
                  {hasMcqScore ? `${mcq.score}/${mcq.maxScore}` : mcq?.available ? "Not scanned" : "N/A"}
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Essay Score</p>
                <p className="mt-1 text-xl font-extrabold text-[#291C57]">
                  {essay?.available ? `${essay.score ?? "—"}/${essay.maxScore ?? "—"}` : "N/A"}
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Final Score</p>
                <p className="mt-1 text-xl font-extrabold text-emerald-600">
                  {finalScore !== null && finalScore !== undefined ? `${finalScore}${data.maxScore ? `/${data.maxScore}` : ""}` : "Pending"}
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Student sees</p>
                <p className={`mt-1 text-sm font-bold ${released ? "text-emerald-600" : "text-slate-500"}`}>
                  {released ? "Released" : "Hidden"}
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div><h2 className="font-bold text-[#0B1739]">Page 1 — Scanned answer sheet</h2><p className="text-xs text-slate-500">Original image used for OMR bubble detection.</p></div>
            </div>
            <div className="flex min-h-[280px] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 overflow-hidden">
              {page1Url ? (
                <img src={page1Url} alt="Scanned Page 1" className="max-h-[520px] w-auto object-contain" />
              ) : (
                <div className="text-center text-slate-400">
                  <i className="bx bxs-image text-5xl" />
                  <p className="mt-2 text-xs">{imgError || (data.files?.page1 ? "Loading scanned page…" : "No Page 1 was uploaded for this exam.")}</p>
                </div>
              )}
            </div>
          </section>

          {mcq?.available && (
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
              <div className="mb-4 flex items-center justify-between">
                <div><h2 className="font-bold text-[#0B1739]">MCQ answer breakdown</h2><p className="text-xs text-slate-500">Detected from the OpenCV OMR pipeline.</p></div>
                {!mcq.omrAvailable && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-bold text-amber-600">OMR engine unavailable</span>}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-sm">
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

        <aside className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <h2 className="font-bold text-[#0B1739]">Processing status</h2>
            <div className="mt-4 space-y-3">
              <div className="flex items-center gap-3"><i className="bx bxs-check-circle text-lg text-emerald-500" /><span className="text-sm text-slate-600">Image uploaded</span></div>
              <div className="flex items-center gap-3">
                <i className={`bx bxs-check-circle text-lg ${mcq?.available ? "text-emerald-500" : "text-slate-300"}`} />
                <span className="text-sm text-slate-600">{mcq?.available ? `MCQ scored (${mcq.omrAvailable ? "OpenCV OMR" : "OMR unavailable"})` : "No MCQ portion"}</span>
              </div>
              <div className="flex items-center gap-3">
                <i className={`bx bxs-check-circle text-lg ${essay?.available && essay?.combinedText ? "text-emerald-500" : "text-slate-300"}`} />
                <span className="text-sm text-slate-600">{essay?.available ? "Essay OCR completed" : "No essay portion"}</span>
              </div>
              <div className="flex items-center gap-3">
                <i className={`bx bxs-check-circle text-lg ${essay?.available && essay?.score !== null && essay?.score !== undefined ? "text-emerald-500" : "text-slate-300"}`} />
                <span className="text-sm text-slate-600">
                  {essay?.available
                    ? `Essay graded (spaCy NLP)${overriddenCount ? ` · ${overriddenCount} manually adjusted` : ""}`
                    : "No essay grading needed"}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <i className={`bx ${released ? "bxs-check-circle text-emerald-500" : "bx-hide text-slate-300"} text-lg`} />
                <span className="text-sm text-slate-600">
                  {released ? "Score released to the student" : "Score not released to the student"}
                </span>
              </div>
            </div>
          </section>

          <button
            onClick={() => navigate(`/Professor/classes/${classId}/exams/${examId}/students/${studentId}/details`)}
            disabled={processing || failed}
            className="w-full rounded-xl bg-[#291C57] px-4 py-3 text-sm font-bold text-white shadow-sm hover:bg-[#211645] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {essay?.available ? "Grade essays & release score" : "Review & release score"} <i className="bx bx-right-arrow-alt ml-1" />
          </button>
          <p className="text-center text-[11px] leading-5 text-slate-400">
            {processing
              ? "Available once grading finishes."
              : failed
              ? "Re-scan this sheet before it can be graded."
              : essay?.available
              ? "Adjust individual essay scores, then release the result to the student."
              : "Release the result so the student can see their score."}
          </p>
        </aside>
      </div>
    </PageShell>
  );
}

export default ExamStudentSubmission;
