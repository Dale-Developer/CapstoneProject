import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, PageShell } from "../../../components/prof/PageShell";
import { downloadExamPdf, getExams, previewExamPdf, openBlobInNewTab } from "../../../api/examsApi";

function Exams() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloadingId, setDownloadingId] = useState(null);
  const [viewingId, setViewingId] = useState(null);

  const loadExams = async () => {
    setLoading(true);
    setError("");
    try {
      setExams(await getExams());
    } catch (err) {
      setError(err.message || "Unable to load examinations.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExams();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return exams.filter(
      (exam) =>
        !q ||
        `${exam.title} ${exam.className} ${exam.section || ""} ${exam.subject}`
          .toLowerCase()
          .includes(q)
    );
  }, [search, exams]);

  const handleView = async (exam) => {
    setViewingId(exam.id);
    setError("");
    try {
      const payload = {
        title: exam.title,
        subject: exam.subject,
        classIds: [Number(exam.classId)],
        mcqQuestions: (exam.mcqQuestions || []).map(q => ({
          question: q.question,
          options: q.options || ["", "", "", "", ""],
          correctAnswer: q.correctAnswer,
          points: Number(q.points) || 1,
        })),
        essayQuestions: (exam.essayQuestions || []).map(q => ({
          question: q.question,
          answerKey: q.answerKey || "",
          keyConcepts: q.keyConcepts || [],
          keywords: q.keywords || [],
          requirements: q.requirements || [],
          points: Number(q.points) || 10,
          expectedResponseFormat: "one_paragraph",
          rubric: (q.rubric || exam.rubric || []).map(r => ({
            name: r.name,
            weight: Number(r.weight) || 0,
          })),
        })),
        status: exam.status || "Draft",
      };
      const blob = await previewExamPdf(payload);
      openBlobInNewTab(blob);
    } catch (err) {
      setError(err.message || "Unable to open the printable preview.");
    } finally {
      setViewingId(null);
    }
  };

  const handleDownload = async (examId) => {
    setDownloadingId(examId);
    try {
      await downloadExamPdf(examId);
    } catch (err) {
      setError(err.message || "Unable to generate the exam PDF.");
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <PageShell>
      <PageHeader
        title="Examinations"
        description="Create, manage, and print examinations across your classes."
        action={
          <button
            onClick={() => navigate("/Professor/exams/createexam")}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#211645]"
          >
            <i className="bx bx-plus text-lg" />
            Create exam
          </button>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mb-5 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="relative">
          <i className="bx bx-search absolute left-4 top-1/2 -translate-y-1/2 text-lg text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search exam, class, section, or subject"
            className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-11 pr-4 text-sm text-slate-800 outline-none transition focus:border-[#291C57] focus:bg-white focus:ring-4 focus:ring-[#291C57]/10"
          />
        </div>
      </div>

      {loading ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">
          Loading examinations...
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
          <i className="bx bx-file-blank text-4xl text-slate-300" />
          <h2 className="mt-3 font-bold text-[#0B1739]">No examinations found</h2>
          <p className="mt-1 text-sm text-slate-500">
            Create an examination to generate its printable answer sheet.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {filtered.map((exam) => (
            <article
              key={exam.id}
              className="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
            >
              <button
                onClick={() =>
                  navigate(`/Professor/classes/${exam.classId}/exams/${exam.id}`)
                }
                className="w-full text-left"
              >
                <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-4">
                  <div className="min-w-0">
                    <span className="inline-flex items-center rounded-full bg-[#F1EFF7] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#291C57]">
                      {exam.section || "Class"}
                    </span>
                    <h2 className="mt-2 line-clamp-2 text-sm font-bold leading-5 text-[#0B1739]">
                      {exam.title}
                    </h2>
                    <p className="mt-1 truncate text-xs text-slate-500">
                      {exam.subject} · {exam.className}
                    </p>
                  </div>
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-blue-50 text-xl text-[#1A73E8]">
                    <i className="bx bxs-file" />
                  </span>
                </div>

                <div className="flex items-center justify-between gap-3 px-4 py-3.5 text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <i className="bx bx-file" />
                    Paper-based major exam
                  </span>
                  <span>{exam.totalItems} items · {exam.totalPoints} pts</span>
                </div>
              </button>

              <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3">
                <button
                  onClick={() =>
                    navigate(`/Professor/exams/edit/${exam.id}`)
                  }
                  className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-500 transition hover:text-[#291C57]"
                >
                  <i className="bx bx-edit-alt" />
                  Edit
                </button>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleView(exam)}
                    disabled={viewingId === exam.id}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[#291C57] px-3 py-2 text-xs font-bold text-[#291C57] transition hover:bg-[#F8F6FC] disabled:opacity-60"
                  >
                    <i className={`bx ${viewingId === exam.id ? "bx-loader-alt bx-spin" : "bx-show"}`} />
                    {viewingId === exam.id ? "Opening..." : "View"}
                  </button>
                  <button
                    onClick={() => handleDownload(exam.id)}
                    disabled={downloadingId === exam.id}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#291C57] px-3 py-2 text-xs font-bold text-white transition hover:bg-[#211645] disabled:cursor-wait disabled:opacity-60"
                  >
                    <i className={`bx ${downloadingId === exam.id ? "bx-loader-alt bx-spin" : "bxs-file-pdf"}`} />
                    {downloadingId === exam.id ? "Generating..." : "Download PDF"}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </PageShell>
  );
}

export default Exams;
