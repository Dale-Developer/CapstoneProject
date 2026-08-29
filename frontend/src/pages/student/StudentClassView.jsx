import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getClass } from "../../api/classesApi";
import { PageHeader, PageShell, BackButton } from "../../components/prof/PageShell";

export default function StudentClassView() {
  const { classId } = useParams(); const navigate = useNavigate();
  const [cls, setCls] = useState(null); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  useEffect(() => { getClass(classId).then(setCls).catch(e => setError(e.message || "Unable to load class.")).finally(() => setLoading(false)); }, [classId]);
  if (loading) return <PageShell><div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading class...</div></PageShell>;
  if (error || !cls) return <PageShell><div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{error || "Class not found."}</div></PageShell>;
  const exams = cls.examList || [];
  return <PageShell><BackButton onClick={() => navigate("/student")} /><PageHeader title={`${cls.section ? cls.section + " – " : ""}${cls.title}`} description={`${cls.subject} · ${exams.length} examination${exams.length === 1 ? "" : "s"}`} />
    <section className="mb-6 overflow-hidden rounded-2xl p-5 text-white shadow-[0_8px_24px_rgba(41,28,87,0.12)] sm:p-6" style={{backgroundColor: cls.color || "#291C57"}}><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-white/65">{cls.section || "Class"}</p><h2 className="mt-1 text-xl font-bold">{cls.title}</h2><p className="mt-2 text-sm text-white/80">{cls.subject}</p></section>
    <div className="mb-4"><h2 className="text-lg font-bold text-[#0B1739]">Examinations</h2><p className="text-xs text-slate-500">Only examinations assigned to this class are shown.</p></div>
    {exams.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center text-sm text-slate-500">No examinations have been assigned yet.</div> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{exams.map(exam => <button key={exam.id} onClick={() => navigate(`/student/class/${classId}/exam/${exam.id}`)} className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:-translate-y-0.5 hover:shadow-md"><div className="flex items-start justify-between"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-xl text-[#1A73E8]"><i className="bx bxs-file" /></span><i className="bx bx-chevron-right text-xl text-slate-300 group-hover:text-[#291C57]" /></div><h3 className="mt-4 line-clamp-2 text-sm font-bold text-[#0B1739]">{exam.title}</h3><div className="mt-3 flex items-center justify-between text-xs text-slate-500"><span>{exam.date ? new Date(`${exam.date}T00:00:00`).toLocaleDateString() : "No date"}</span><span>View exam</span></div></button>)}</div>}
  </PageShell>;
}
