import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { downloadExamPdf, getExam, getExamSubmissions, releaseExamScores } from "../../../api/examsApi";
import {
  BackButton,
  PageHeader,
  PageShell,
  StatCard,
} from "../../../components/prof/PageShell";

const initials = (name) =>
  String(name || "")
    .split(" ")
    .map((n) => n[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

function ExamView() {
  const { classId, examId } = useParams();
  const navigate = useNavigate();
  const [exam, setExam] = useState(null);
  const [submissions, setSubmissions] = useState([]);
  const [filter, setFilter] = useState("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [printing, setPrinting] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");

    Promise.all([getExam(examId), getExamSubmissions(examId)])
      .then(([examData, submissionData]) => {
        if (!active) return;
        setExam(examData);
        setSubmissions(Array.isArray(submissionData) ? submissionData : []);
      })
      .catch((err) => {
        if (active) setError(err.message || "Unable to load the examination.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [examId]);

  const reload = () =>
    getExamSubmissions(examId)
      .then((rows) => setSubmissions(Array.isArray(rows) ? rows : []))
      .catch(() => {});

  const releasable = submissions.filter((s) => s.score !== null && s.score !== undefined);
  const unreleased = releasable.filter((s) => !s.scoresReleased);
  const releasedCount = releasable.length - unreleased.length;

  const handleRelease = async (released) => {
    const count = released ? unreleased.length : releasedCount;
    if (!count) return;
    const ok = window.confirm(
      released
        ? `Release ${count} score(s) to students?\n\nEach student will be able to see their final score, their answers and the answer key.`
        : `Hide ${count} released score(s) from students?`
    );
    if (!ok) return;

    setReleasing(true); setNotice(""); setError("");
    try {
      const result = await releaseExamScores(examId, { released });
      setNotice(result.message || "Done.");
      await reload();
    } catch (err) {
      setError(err.message || "Unable to change the release state.");
    } finally {
      setReleasing(false);
    }
  };

  const stats = useMemo(() => {
    const graded = submissions.filter((s) => s.status === "Graded" || s.status === "Released").length;
    const processing = submissions.filter((s) =>
      ["OCR_Processing", "NLP_Processing", "Uploaded", "OCR_Completed"].includes(s.status)
    ).length;
    const failed = submissions.filter((s) => s.status === "Failed").length;

    return {
      graded,
      processing,
      failed,
      total: exam?.students ?? submissions.length,
    };
  }, [exam, submissions]);

  const filtered =
    filter === "All"
      ? submissions
      : submissions.filter((student) => student.status === filter);

  const filters = ["All", "Released", "Graded", "OCR_Processing", "Failed", "Pending"];

  const handlePrint = async () => {
    setPrinting(true);
    try {
      await downloadExamPdf(examId);
    } catch (err) {
      setError(err.message || "Unable to generate the answer sheet.");
    } finally {
      setPrinting(false);
    }
  };

  if (loading) {
    return (
      <PageShell>
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">
          Loading examination...
        </div>
      </PageShell>
    );
  }

  if (error || !exam) {
    return (
      <PageShell>
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">
          {error || "Exam not found."}
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <BackButton onClick={() => navigate(-1)} />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <PageHeader
        title={exam.title}
        description={`${exam.subject} · ${exam.section || exam.className} · ${exam.totalItems} items`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => navigate(`/Professor/upload?examId=${examId}`)}
              className="inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white hover:bg-[#211645]"
            >
              <i className="bx bx-scan" /> Scan answer sheet
            </button>
            <button
              onClick={handlePrint}
              disabled={printing}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-60"
            >
              <i className={`bx ${printing ? "bx-loader-alt bx-spin" : "bxs-file-pdf"}`} />
              {printing ? "Generating..." : "Print answer sheet"}
            </button>
            {releasedCount > 0 && (
              <button
                onClick={() => handleRelease(false)}
                disabled={releasing}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-60"
              >
                <i className="bx bx-hide" /> Hide all
              </button>
            )}
            <button
              onClick={() => handleRelease(true)}
              disabled={releasing || unreleased.length === 0}
              className="inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40"
              title={unreleased.length === 0 ? "Every scored submission has already been released." : undefined}
            >
              <i className={`bx ${releasing ? "bx-loader-alt bx-spin" : "bx-send"}`} />
              {releasing ? "Working..." : `Release ${unreleased.length || ""} score${unreleased.length === 1 ? "" : "s"}`.trim()}
            </button>
          </div>
        }
      />

      {notice && (
        <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <StatCard label="Graded" value={stats.graded} description="Completed submissions" icon="bxs-check-circle" iconClass="bg-emerald-50 text-emerald-600" />
        <StatCard label="Processing" value={stats.processing} description="OCR / NLP in progress" icon="bx-time-five" iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Released" value={releasedCount} description="Visible to students" icon="bx-send" iconClass="bg-[#F1EFF7] text-[#291C57]" />
        <StatCard label="Failed" value={stats.failed} description="Needs a re-scan" icon="bx-error-circle" iconClass={stats.failed > 0 ? "bg-rose-50 text-rose-600" : "bg-slate-100 text-slate-400"} />
        <StatCard label="Total students" value={stats.total} description="Expected submissions" icon="bxs-group" />
      </div>

      {stats.failed > 0 && (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <i className="bx bx-error-circle mt-0.5 shrink-0" />
          <span>
            {stats.failed} submission{stats.failed === 1 ? "" : "s"} failed to process and{" "}
            {stats.failed === 1 ? "needs" : "need"} to be re-scanned.{" "}
            <button type="button" onClick={() => setFilter("Failed")} className="font-bold underline underline-offset-2">
              Show failed submissions
            </button>
          </span>
        </div>
      )}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 p-4 sm:p-5">
          <h2 className="font-bold text-[#0B1739]">Student submissions</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Select a student to review the processed answer sheet.
          </p>

          <div className="mt-4 -mx-1 overflow-x-auto px-1 pb-1">
            <div className="flex w-max gap-1.5">
              {filters.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setFilter(name)}
                  className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${
                    filter === name ? "bg-[#291C57] text-white" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="divide-y divide-slate-100">
          {filtered.length === 0 ? (
            <div className="px-6 py-14 text-center text-sm text-slate-500">
              No submissions found for this filter.
            </div>
          ) : (
            filtered.map((student, index) => {
              const isFailed = student.status === "Failed";
              const isProcessing = ["OCR_Processing", "NLP_Processing", "Uploaded", "OCR_Completed"].includes(student.status);
              return (
                <button
                  key={student.id}
                  type="button"
                  onClick={() =>
                    navigate(`/Professor/classes/${classId}/exams/${examId}/students/${student.studentId}`)
                  }
                  className="flex w-full items-center gap-3 px-4 py-4 text-left transition hover:bg-slate-50 sm:px-5"
                >
                  <span className="hidden w-5 shrink-0 text-center text-xs font-bold text-slate-400 sm:inline">{index + 1}</span>
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#291C57] text-xs font-bold text-white">
                    {initials(student.studentName)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-bold text-[#0B1739]">{student.studentName}</p>
                    <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                      {isFailed && <i className="bx bx-error-circle shrink-0 text-rose-500" />}
                      {isProcessing && <i className="bx bx-loader-alt bx-spin shrink-0 text-amber-500" />}
                      <span className="truncate">
                        {isFailed ? "Failed — needs re-scan" : isProcessing ? "Grading…" : student.status}
                        {student.overriddenCount > 0 && ` · ${student.overriddenCount} adjusted`}
                      </span>
                    </p>
                  </div>
                  <span className={`shrink-0 text-sm font-extrabold ${isFailed ? "text-rose-500" : "text-[#291C57]"}`}>
                    {isFailed ? <i className="bx bx-error-circle text-lg" /> : student.score != null ? `${student.score}${student.maxScore ? `/${student.maxScore}` : ""}` : "—"}
                  </span>
                  <span
                    className={`hidden shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold sm:inline ${student.scoresReleased ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}
                  >
                    {student.scoresReleased ? "Released" : "Hidden"}
                  </span>
                  <i className="bx bx-chevron-right shrink-0 text-lg text-slate-300" />
                </button>
              );
            })
          )}
        </div>
      </section>
    </PageShell>
  );
}

export default ExamView;
