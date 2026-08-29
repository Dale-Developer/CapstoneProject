import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getStudentExam, getStudentExams, uploadStudentAnswerSheet } from "../../api/studentApi";
import { PageHeader, PageShell, BackButton } from "../../components/prof/PageShell";
import CameraScanner from "../../components/common/CameraScanner";
import FileDropBox from "../../components/common/FileDropBox";

// The printable answer sheet places a maximum of 2 essay answers per page,
// so the number of essay pages to upload scales with the essay question count.
const ESSAYS_PER_PAGE = 2;

export default function StudentUpload() {
  const { classId, examId } = useParams();
  const navigate = useNavigate();
  const [exams, setExams] = useState([]);
  const [exam, setExam] = useState(null);
  const [page1, setPage1] = useState(null);
  const [essayPages, setEssayPages] = useState([]); // one entry per required essay page
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);
  const [cameraTarget, setCameraTarget] = useState(null); // "page1" | "essay-<index>" | null

  useEffect(() => {
    if (examId) {
      getStudentExam(examId)
        .then(setExam)
        .catch((e) => setError(e.message || "Unable to load examination."));
    } else {
      getStudentExams()
        .then(setExams)
        .catch((e) => setError(e.message || "Unable to load your examinations."));
    }
  }, [examId]);

  const hasMcq = Boolean(exam?.questions?.some((q) => q.type === "MCQ"));
  const essayCount = exam?.questions?.filter((q) => q.type === "Essay").length || 0;
  const hasEssay = essayCount > 0;
  const essayPageCount = Math.ceil(essayCount / ESSAYS_PER_PAGE);

  // A processed submission is final for the student. The form is replaced by
  // a read-only notice rather than merely disabled, so there is no ambiguity
  // about whether another attempt is possible.
  const submission = exam?.submission;
  const locked = Boolean(submission?.locked);

  // Keep the essay-page slot count in sync with the loaded exam's essay count.
  useEffect(() => {
    setEssayPages((prev) => {
      if (prev.length === essayPageCount) return prev;
      return Array.from({ length: essayPageCount }, (_, i) => prev[i] || null);
    });
  }, [essayPageCount]);

  if (!examId) {
    return (
      <PageShell>
        <PageHeader title="Upload Answer Sheet" description="Choose an examination, then upload the required answer-sheet pages." />
        {error && <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {exams.length === 0 && !error ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center text-sm text-slate-500">No examinations are available for upload yet.</div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {exams.map((item) => (
              <button key={item.id} onClick={() => navigate(`/student/class/${item.classId}/exam/${item.id}/upload`)} className="rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
                <div className="flex items-center justify-between">
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-[#F1EFF7] text-xl text-[#291C57]"><i className="bx bx-scan" /></span>
                  <i className="bx bx-chevron-right text-xl text-slate-300" />
                </div>
                <h2 className="mt-4 text-sm font-bold text-[#0B1739]">{item.title}</h2>
                <p className="mt-1 text-xs text-slate-500">{item.subject} · {item.totalItems} items</p>
                <span className={`mt-4 inline-flex rounded-lg px-3 py-2 text-xs font-bold ${item.locked ? "bg-slate-100 text-slate-500" : "bg-[#291C57] text-white"}`}>
                  {item.locked ? "Already submitted" : "Upload answer sheet"}
                </span>
              </button>
            ))}
          </div>
        )}
      </PageShell>
    );
  }

  const essayPagesComplete = !hasEssay || (essayPages.length === essayPageCount && essayPages.every(Boolean));

  const setEssayPageAt = (index, file) => {
    setEssayPages((prev) => {
      const next = [...prev];
      next[index] = file;
      return next;
    });
  };

  const clearAll = () => {
    setPage1(null);
    setEssayPages(Array.from({ length: essayPageCount }, () => null));
  };

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setSuccess("");
    if (hasMcq && !page1) return setError("Please select Page 1 (multiple choice) of your answer sheet.");
    if (hasEssay && !essayPagesComplete) return setError(`Please select all ${essayPageCount} essay answer page${essayPageCount === 1 ? "" : "s"}.`);

    // This is the student's only attempt, so it is worth one deliberate
    // confirmation rather than an accidental tap on a phone.
    const confirmed = window.confirm(
      "Submit your answer sheet?\n\nYou can only submit once. After submitting you will not be able to upload or replace it — you would need to ask your professor to re-scan it for you."
    );
    if (!confirmed) return;

    setSaving(true);
    try {
      const result = await uploadStudentAnswerSheet({
        examId,
        page1: hasMcq ? page1 : null,
        essayPages: hasEssay ? essayPages : [],
      });
      setSuccess(result.message || "Answer sheet submitted.");
      clearAll();
      // Refresh so the page switches to its locked state immediately.
      getStudentExam(examId).then(setExam).catch(() => {});
    } catch (e) {
      setError(e.message || "Unable to upload answer sheet.");
      // A 409 means the sheet was locked between loading the page and
      // submitting; re-fetch so the UI stops offering an impossible action.
      if (/already submitted/i.test(e.message || "")) {
        getStudentExam(examId).then(setExam).catch(() => {});
      }
    } finally { setSaving(false); }
  };

  if (!exam && !error) return <PageShell><div className="px-6 py-16 text-center text-sm text-slate-500">Loading examination...</div></PageShell>;

  const submitDisabled = saving || locked || (hasMcq && !page1) || (hasEssay && !essayPagesComplete);
  const selectedCount = (page1 ? 1 : 0) + essayPages.filter(Boolean).length;
  const requiredCount = (hasMcq ? 1 : 0) + essayPageCount;

  return (
    <PageShell>
      <BackButton onClick={() => navigate(`/student/class/${classId}/exam/${examId}`)} />
      <PageHeader
        title="Upload Answer Sheet"
        description={exam ? `${exam.title} · Your answer sheet will be automatically named using your student information.` : "Upload your answer sheet."}
      />

      {error && <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

      {locked && (
        <div className="mb-5 max-w-3xl rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl text-2xl ${
              submission?.failed ? "bg-rose-50 text-rose-600"
              : submission?.processing ? "bg-amber-50 text-amber-600"
              : "bg-emerald-50 text-emerald-600"
            }`}>
              <i className={`bx ${submission?.failed ? "bx-error-circle" : submission?.processing ? "bx-time-five" : "bx-check-shield"}`} />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-bold text-[#0B1739]">
                {submission?.failed
                  ? "We couldn't process your answer sheet"
                  : submission?.processing
                  ? "Your answer sheet is being graded"
                  : "Your answer sheet has already been submitted"}
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                {submission?.failed ? (
                  "Something went wrong while reading your sheet. This has been recorded and your professor can re-scan it for you — no action is needed from you."
                ) : submission?.processing ? (
                  <>
                    It was received{submission?.submittedAt ? ` on ${new Date(submission.submittedAt).toLocaleString()}` : ""} and
                    is being scanned and graded now. This page will show your score once your professor releases it.
                  </>
                ) : (
                  <>
                    It was received and processed
                    {submission?.submittedAt ? ` on ${new Date(submission.submittedAt).toLocaleString()}` : ""}.
                    You cannot upload another one. If something is wrong with your scan, ask your professor to re-scan it for you.
                  </>
                )}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {!submission?.failed && (
                  <button
                    onClick={() => navigate(`/student/class/${classId}/exam/${examId}/result`)}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white"
                  >
                    <i className="bx bx-award" /> {submission?.processing ? "Check status" : "View my score"}
                  </button>
                )}
                <button
                  onClick={() => navigate(`/student/class/${classId}/exam/${examId}`)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50"
                >
                  Back to examination
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {exam && !locked && (
        <form onSubmit={submit} className="max-w-3xl">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-5 rounded-xl bg-[#F7F4FC] px-4 py-3 text-sm text-[#291C57]">
              <i className="bx bx-info-circle mr-2" />
              Upload only the answer sheet pages. Check each preview before submitting — you can delete and retake any page.
              {hasEssay && ` This exam needs ${essayPageCount} essay answer page${essayPageCount === 1 ? "" : "s"} (2 essay answers per page).`}
            </div>

            <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <i className="bx bx-lock-alt mr-2" />
              You can submit your answer sheet <span className="font-bold">once</span>. After it is processed you will not be able to replace it.
            </div>

            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-400">
                Pages {selectedCount} of {requiredCount} ready
              </p>
              {selectedCount > 0 && (
                <button
                  type="button"
                  onClick={clearAll}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-bold text-slate-500 hover:bg-slate-50 hover:text-rose-600"
                >
                  <i className="bx bx-trash" /> Clear all
                </button>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {hasMcq && (
                <FileDropBox
                  label="Answer Sheet — Page 1"
                  file={page1}
                  onChange={setPage1}
                  onScan={() => setCameraTarget("page1")}
                />
              )}
              {essayPages.map((file, index) => (
                <FileDropBox
                  key={index}
                  label={`Essay Page ${index + 1}${essayPageCount > 1 ? ` of ${essayPageCount}` : ""}`}
                  file={file}
                  onChange={(f) => setEssayPageAt(index, f)}
                  onScan={() => setCameraTarget(`essay-${index}`)}
                />
              ))}
            </div>

            <CameraScanner
              open={!!cameraTarget}
              examId={examId}
              pageNumber={cameraTarget === "page1" ? 1 : cameraTarget?.startsWith("essay-") ? 2 + Number(cameraTarget.split("-")[1]) : 1}
              onClose={() => setCameraTarget(null)}
              onCapture={(file) => {
                if (cameraTarget === "page1") setPage1(file);
                else if (cameraTarget?.startsWith("essay-")) setEssayPageAt(Number(cameraTarget.split("-")[1]), file);
                setCameraTarget(null);
              }}
              onError={(msg) => setError(msg)}
              instructions={`Match the 4 squares to the 4 corner squares on ${cameraTarget === "page1" ? "Page 1" : "the essay page"}`}
            />

            {success && <div className="mt-4 rounded-xl bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">{success}</div>}

            <button disabled={submitDisabled} className="mt-5 w-full rounded-xl bg-[#291C57] px-4 py-3 text-sm font-bold text-white disabled:opacity-40">
              {saving ? "Submitting..." : "Submit answer sheet"}
            </button>
            {saving && (
              <p className="mt-2 text-center text-xs text-slate-500">
                Saving your pages — this only takes a moment.
              </p>
            )}
            {!saving && (
              <p className="mt-2 text-center text-xs text-slate-400">
                Grading happens afterward. You'll see your score once your professor releases it.
              </p>
            )}
          </div>
        </form>
      )}
    </PageShell>
  );
}
