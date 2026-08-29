import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader, PageShell } from "../../../components/prof/PageShell";
import { getSubmissionStatus, matchAnswerSheetOwner, uploadAnswerSheetForStudent } from "../../../api/uploadsApi";
import { getExams } from "../../../api/examsApi";
import CameraScanner from "../../../components/common/CameraScanner";
import FileDropBox from "../../../components/common/FileDropBox";

// The printable answer sheet places a maximum of 2 essay answers per page,
// so the number of essay pages to upload scales with the essay question count.
const ESSAYS_PER_PAGE = 2;

function Upload() {
  const navigate = useNavigate();
  // Arriving from an exam's page (via "Scan for this exam") pre-selects that
  // exam instead of leaving the professor to find it again in the dropdown.
  const [searchParams] = useSearchParams();
  const [examId, setExamId] = useState(searchParams.get("examId") || "");
  const [exams, setExams] = useState([]);
  const [loadingExams, setLoadingExams] = useState(true);

  const [page1, setPage1] = useState(null);
  const [essayPages, setEssayPages] = useState([]); // one entry per required essay page
  const [cameraTarget, setCameraTarget] = useState(null); // "page1" | "essay-<index>" | null

  const [matching, setMatching] = useState(false);
  const [matchResult, setMatchResult] = useState(null); // { ocrAvailable, ocrText, candidates, roster }
  const [studentId, setStudentId] = useState("");
  const [search, setSearch] = useState("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Every recently-scanned sheet, newest first, so a professor can keep
  // scanning without leaving the page and still see when each one finishes
  // grading (or fails) in the background. Capped so the list stays scannable.
  const [recentUploads, setRecentUploads] = useState([]);

  // Existing-submission state for the confirmed student, so the professor is
  // warned about replacing a processed sheet before uploading rather than
  // after the pipeline has already run.
  const [existing, setExisting] = useState(null);

  useEffect(() => {
    let active = true;
    getExams()
      .then((items) => { if (active) setExams(items); })
      .catch((err) => { if (active) setError(err.message || "Unable to load examinations."); })
      .finally(() => { if (active) setLoadingExams(false); });
    return () => { active = false; };
  }, []);

  const selectedExam = exams.find((exam) => String(exam.id) === String(examId));
  const hasMcq = Boolean(selectedExam?.mcqQuestions?.length);
  const essayCount = selectedExam?.essayQuestions?.length || 0;
  const hasEssay = essayCount > 0;
  const essayPageCount = Math.ceil(essayCount / ESSAYS_PER_PAGE);
  const requiresPage1 = hasMcq;
  const identificationFile = hasMcq ? page1 : essayPages[0];

  // Re-run OCR matching as soon as the identification page changes.
  useEffect(() => {
    if (!examId || !identificationFile) { setMatchResult(null); setStudentId(""); return undefined; }
    let active = true;
    // Actually cancel the in-flight request when a new photo replaces this
    // one before identification finishes, instead of just ignoring its
    // result — a discarded photo's OCR/Ollama call was still burning real
    // backend time for nothing until this was added.
    const controller = new AbortController();
    setMatching(true);
    setError("");
    matchAnswerSheetOwner({
      examId,
      page1: hasMcq ? page1 : null,
      essayPages: hasMcq ? [] : essayPages.slice(0, 1),
      signal: controller.signal,
    })
      .then((result) => {
        if (!active) return;
        setMatchResult(result);
        // Pre-select the top candidate only if it's a confident guess; otherwise
        // leave it for the professor to choose deliberately.
        const top = result.candidates?.[0];
        setStudentId(top && top.confidence >= 0.55 ? String(top.id) : "");
      })
      .catch((err) => {
        if (!active || err?.name === "AbortError") return;
        setError(err.message || "Unable to identify the student from the answer sheet.");
      })
      .finally(() => { if (active) setMatching(false); });
    return () => { active = false; controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examId, identificationFile, hasMcq]);

  // Keep the essay-page slot count in sync with the selected exam's essay count.
  useEffect(() => {
    setEssayPages((prev) => {
      if (prev.length === essayPageCount) return prev;
      const next = Array.from({ length: essayPageCount }, (_, i) => prev[i] || null);
      return next;
    });
  }, [essayPageCount]);

  useEffect(() => {
    if (!examId || !studentId) { setExisting(null); return; }
    let active = true;
    getSubmissionStatus(examId, studentId)
      .then((res) => { if (active) setExisting(res); })
      .catch(() => { if (active) setExisting(null); });
    return () => { active = false; };
  }, [examId, studentId]);

  const selectedStudent = matchResult?.roster?.find((s) => String(s.id) === String(studentId));

  const filteredRoster = useMemo(() => {
    const roster = matchResult?.roster || [];
    if (!search.trim()) return roster;
    const q = search.trim().toLowerCase();
    return roster.filter((s) => s.name.toLowerCase().includes(q) || s.email.toLowerCase().includes(q));
  }, [matchResult, search]);

  const resetForm = () => {
    setPage1(null);
    setEssayPages(Array.from({ length: essayPageCount }, () => null));
    setCameraTarget(null);
    setMatchResult(null); setStudentId(""); setSearch(""); setExisting(null);
  };

  const setEssayPageAt = (index, file) => {
    setEssayPages((prev) => {
      const next = [...prev];
      next[index] = file;
      return next;
    });
  };

  const essayPagesComplete = !hasEssay || (essayPages.length === essayPageCount && essayPages.every(Boolean));

  // Poll only the entries still being graded, and only while any exist. Each
  // tick reschedules itself via the recentUploads dependency, so this stops
  // automatically once every visible sheet is Graded, Released, or Failed —
  // no interval to leak, nothing to clean up beyond the single timer.
  useEffect(() => {
    const pending = recentUploads.filter((u) => u.processing);
    if (pending.length === 0) return undefined;

    const timer = setTimeout(async () => {
      const results = await Promise.all(
        pending.map((u) =>
          getSubmissionStatus(u.examId, u.studentId)
            .then((res) => ({ key: u.key, res }))
            .catch(() => null)
        )
      );
      setRecentUploads((prev) =>
        prev.map((item) => {
          const found = results.find((r) => r && r.key === item.key);
          if (!found) return item;
          return {
            ...item,
            status: found.res.status,
            processing: Boolean(found.res.processing),
            failed: Boolean(found.res.failed),
            error: found.res.error || null,
            finalScore: found.res.finalScore,
            maxScore: found.res.maxScore,
          };
        })
      );
    }, 3000);

    return () => clearTimeout(timer);
  }, [recentUploads]);

  async function handleSubmit() {
    if (!examId) return setError("Select an examination first.");
    if (requiresPage1 && !page1) return setError("This examination requires the multiple-choice Page 1 answer sheet.");
    if (hasEssay && !essayPagesComplete) return setError(`This examination requires ${essayPageCount} essay answer page${essayPageCount === 1 ? "" : "s"}.`);
    if (!studentId) return setError("Please confirm which student this answer sheet belongs to.");
    // Replacing a processed sheet discards its scores and un-releases it, so
    // it must be an explicit decision rather than a silent overwrite.
    let allowReplace = false;
    if (existing?.locked) {
      const name = selectedStudent?.name || "this student";
      const warning = existing.processing
        ? `${name}'s answer sheet is still being graded from a previous scan.\n\nRe-scanning now will replace it once the new sheet finishes processing.\n\nContinue?`
        : existing.scoresReleased
        ? `${name} already has a processed answer sheet and their score has been RELEASED.\n\nRe-scanning will discard the current scores and hide the result from the student again until you release it once more.\n\nContinue?`
        : `${name} already has a processed answer sheet for this examination.\n\nRe-scanning will discard the current scores, including any manual essay overrides.\n\nContinue?`;
      if (!window.confirm(warning)) return;
      allowReplace = true;
    }

    setError(""); setSuccess(""); setSaving(true);
    try {
      const result = await uploadAnswerSheetForStudent({
        examId,
        studentId,
        page1: requiresPage1 ? page1 : null,
        essayPages: hasEssay ? essayPages : [],
        allowReplace,
      });
      setSuccess(
        `Saved. ${selectedStudent?.name || "This student"}'s sheet is now grading in the background — `
        + "you can scan the next student right away."
      );
      setRecentUploads((prev) => [
        {
          key: result.submissionId ?? `${examId}-${studentId}-${Date.now()}`,
          examId,
          studentId: Number(studentId),
          studentName: selectedStudent?.name || "Student",
          status: result.status || "OCR_Processing",
          processing: result.processing !== false,
          failed: false,
          error: null,
          finalScore: null,
          maxScore: null,
        },
        ...prev,
      ].slice(0, 8));
      resetForm();
    } catch (err) {
      setError(err.message || "Unable to upload the answer sheet.");
    } finally { setSaving(false); }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="Answer Sheet Processing"
        title="Upload Answer Sheet"
        description="Choose an examination, upload only the required answer-sheet page(s), then confirm the student identified by OCR."
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <label className="block text-sm font-bold text-[#0B1739]">Select examination</label>
          <div className="relative mt-3">
            <i className="bx bx-book-open absolute left-4 top-1/2 -translate-y-1/2 text-lg text-slate-400" />
            <select
              value={examId}
              onChange={(e) => { setExamId(e.target.value); resetForm(); }}
              className="w-full appearance-none rounded-xl border border-slate-200 bg-slate-50 py-3 pl-11 pr-10 text-sm font-semibold text-slate-700 outline-none focus:border-[#291C57] focus:bg-white focus:ring-4 focus:ring-[#291C57]/10"
            >
              <option value="">{loadingExams ? "Loading examinations..." : "Choose an examination..."}</option>
              {exams.map((exam) => (
                <option key={exam.id} value={exam.id}>
                  {exam.className || "Class"}{exam.section ? ` · ${exam.section}` : ""} — {exam.title}
                </option>
              ))}
            </select>
            <i className="bx bx-chevron-down pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-lg text-slate-400" />
          </div>

          {examId && (
            <>
              <div className="mt-5 rounded-xl bg-[#F7F4FC] px-4 py-3 text-sm text-[#291C57]">
                <i className="bx bx-info-circle mr-2" />
                Upload only the page(s) required by this examination. {hasMcq && hasEssay ? `Page 1 is used for OMR and student identification; the essay pages contain the essay response${essayPageCount === 1 ? "" : "s"} (2 essay answers per page).` : hasMcq ? "Page 1 contains the OMR bubbles and student identification." : `The first essay page also contains student identification. This exam needs ${essayPageCount} essay answer page${essayPageCount === 1 ? "" : "s"} (2 essay answers per page).`}
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {requiresPage1 && (
                  <FileDropBox
                    label="Page 1 — Multiple Choice / OMR"
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
                questionCount={selectedExam?.mcqQuestions?.length || 0}
                onClose={() => setCameraTarget(null)}
                onCapture={(file) => {
                  if (cameraTarget === "page1") setPage1(file);
                  else if (cameraTarget?.startsWith("essay-")) setEssayPageAt(Number(cameraTarget.split("-")[1]), file);
                  setCameraTarget(null);
                }}
                onError={(msg) => setError(msg)}
                instructions={`Automatic ${cameraTarget === "page1" ? "Page 1" : "essay page"} paper detection is active. Keep the whole page visible.`}
              />
            </>
          )}

          {success && <div className="mt-4 flex items-start gap-2 rounded-xl bg-emerald-50 px-3.5 py-3 text-sm text-emerald-700 ring-1 ring-emerald-100"><i className="bx bx-check-circle mt-0.5" />{success}</div>}
          {error && <div className="mt-4 flex items-start gap-2 rounded-xl bg-rose-50 px-3.5 py-3 text-sm text-rose-700 ring-1 ring-rose-100"><i className="bx bx-error-circle mt-0.5" />{error}</div>}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h2 className="font-bold text-[#0B1739]">Confirm student</h2>
          <p className="mt-0.5 text-xs text-slate-500">Required before saving — OCR is a suggestion, not a guarantee.</p>

          {!identificationFile && <p className="mt-6 text-center text-sm text-slate-400">Add the required answer-sheet page to identify the student.</p>}

          {matching && <p className="mt-6 text-center text-sm text-slate-500"><i className="bx bx-loader-alt bx-spin mr-1.5" />Reading {hasMcq ? "Page 1" : "the first essay page"}...</p>}

          {matchResult && !matching && (
            <>
              {(!matchResult.easyocrAvailable || !matchResult.ollamaAvailable) && (
                <div className="mt-4 rounded-xl bg-amber-50 px-3.5 py-3 text-xs text-amber-900 ring-1 ring-amber-100">
                  <p className="font-bold">AI identification status</p>
                  <div className="mt-1 space-y-1">
                    <p>EasyOCR: {matchResult.easyocrAvailable ? "Ready" : "Unavailable"}</p>
                    {!matchResult.easyocrAvailable && matchResult.easyocrError && (
                      <p className="break-words text-rose-700">EasyOCR error: {matchResult.easyocrError}</p>
                    )}
                    <p>Ollama: {matchResult.ollamaAvailable ? "Ready" : "Unavailable"}</p>
                    {!matchResult.ollamaAvailable && matchResult.ollamaError && (
                      <p className="break-words text-rose-700">Ollama error: {matchResult.ollamaError}</p>
                    )}
                  </div>
                  {!matchResult.easyocrAvailable && !matchResult.ollamaAvailable && (
                    <p className="mt-2">You can still select the student manually below. This does not prevent OMR processing.</p>
                  )}
                </div>
              )}

              {matchResult.candidates?.length > 0 && (
                <div className="mt-4 space-y-2">
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Suggested matches</p>
                  {matchResult.candidates.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setStudentId(String(c.id))}
                      className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${String(studentId) === String(c.id) ? "border-[#291C57] bg-[#F7F4FC]" : "border-slate-200 hover:border-slate-300"}`}
                    >
                      <div>
                        <p className="text-sm font-semibold text-[#0B1739]">{c.name}</p>
                        <p className="text-xs text-slate-400">{c.email}</p>
                      </div>
                      <span className={`rounded-full px-2 py-1 text-[10px] font-bold ${c.confidence >= 0.55 ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                        {Math.round(c.confidence * 100)}% match
                      </span>
                    </button>
                  ))}
                </div>
              )}

              <div className="mt-4">
                <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Or search the class roster</p>
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search by name or email..."
                  className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm outline-none focus:border-[#291C57] focus:bg-white focus:ring-4 focus:ring-[#291C57]/10"
                />
                <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
                  {filteredRoster.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => setStudentId(String(s.id))}
                      className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${String(studentId) === String(s.id) ? "bg-[#291C57] text-white" : "hover:bg-slate-50"}`}
                    >
                      <span className="font-medium">{s.name}</span>
                      {String(studentId) === String(s.id) && <i className="bx bx-check" />}
                    </button>
                  ))}
                  {filteredRoster.length === 0 && <p className="px-3 py-2 text-xs text-slate-400">No students match your search.</p>}
                </div>
              </div>
            </>
          )}

          {selectedStudent && (
            <div className="mt-5 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-emerald-100">
              <i className="bx bx-user-check mr-1.5" />Confirmed: <span className="font-bold">{selectedStudent.name}</span>
            </div>
          )}

          {existing?.locked && (
            <div className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900 ring-1 ring-amber-100">
              <p className="font-bold">
                <i className="bx bx-error-circle mr-1" />
                {existing.processing
                  ? "This student's answer sheet is still being graded"
                  : existing.failed
                  ? "This student's answer sheet failed to process"
                  : "This student already has a processed answer sheet"}
              </p>
              <p className="mt-1">
                Submitted {existing.submittedAt ? new Date(existing.submittedAt).toLocaleString() : "previously"}
                {!existing.processing && existing.finalScore !== null && existing.finalScore !== undefined ? ` · Score ${existing.finalScore}` : ""}
                {existing.processing ? " · Grading in progress" : existing.failed ? " · Grading failed" : existing.scoresReleased ? " · Released to the student" : " · Not yet released"}.
              </p>
              {existing.failed && existing.error && (
                <p className="mt-1 break-words text-rose-700">{existing.error}</p>
              )}
              <p className="mt-1">
                {existing.processing
                  ? "Uploading again will replace the sheet currently being graded."
                  : "Uploading again replaces it and discards the current scores, including any manual essay overrides."}
                {" "}You will be asked to confirm.
              </p>
            </div>
          )}

          {existing?.locked && (
            <button
              type="button"
              onClick={() => navigate(`/Professor/classes/${selectedExam?.classId ?? ""}/exams/${examId}/students/${studentId}`)}
              className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-600 hover:bg-slate-50"
            >
              View the existing submission instead
            </button>
          )}

          <button
            onClick={handleSubmit}
            disabled={saving || !examId || (requiresPage1 && !page1) || (hasEssay && !essayPagesComplete) || !studentId}
            className="mt-5 w-full rounded-xl bg-[#291C57] px-4 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#211645] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "Saving..." : existing?.locked ? "Replace answer sheet" : "Save answer sheet"} <i className="bx bx-right-arrow-alt ml-1" />
          </button>
          <p className="mt-2 text-center text-xs text-slate-500">
            Grading (OCR, OMR and essay scoring) runs in the background after saving — you don't have to wait for it before scanning the next student.
          </p>
        </section>
      </div>

      {recentUploads.length > 0 && (
        <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h2 className="font-bold text-[#0B1739]">Recently scanned</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Grading happens in the background. This list updates on its own — no need to stay on this page.
          </p>
          <ul className="mt-4 divide-y divide-slate-100">
            {recentUploads.map((u) => (
              <li key={u.key} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-[#0B1739]">{u.studentName}</p>
                  {u.failed && u.error && (
                    <p className="mt-0.5 truncate text-xs text-rose-600" title={u.error}>{u.error}</p>
                  )}
                </div>
                {u.processing ? (
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-bold text-amber-700">
                    <i className="bx bx-loader-alt bx-spin" /> Grading…
                  </span>
                ) : u.failed ? (
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 text-[11px] font-bold text-rose-700">
                    <i className="bx bx-error-circle" /> Failed — needs re-scan
                  </span>
                ) : (
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-700">
                    <i className="bx bx-check-circle" />
                    Graded{u.finalScore !== null && u.finalScore !== undefined ? ` · ${u.finalScore}/${u.maxScore}` : ""}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </PageShell>
  );
}

export default Upload;
