import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getClass } from "../../../api/classesApi";
import { BackButton, PageHeader, PageShell } from "../../../components/prof/PageShell";

function ClassView() {
  const { classId } = useParams();
  const navigate = useNavigate();
  const [cls, setCls] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    getClass(classId).then((data) => { if (active) setCls(data); }).catch((err) => { if (active) setError(err.message || "Unable to load class."); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [classId]);

  if (loading) return <PageShell><div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading class...</div></PageShell>;
  if (error || !cls) return <PageShell><div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">{error || "Class not found."}</div></PageShell>;

  const exams = cls.examList || [];

  return (
    <PageShell>
      <BackButton onClick={() => navigate(-1)} />
      <PageHeader title={`${cls.section || ""}${cls.section ? " – " : ""}${cls.title}`} description={`${cls.subject} · ${cls.students} students`} action={<button onClick={() => navigate(`/Professor/dashboard/class/${classId}/students`)} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-bold text-[#291C57] shadow-sm hover:bg-[#F8F6FC]"><i className="bx bxs-group" />View students</button>} />
      <section className="mb-6 overflow-hidden rounded-2xl p-5 text-white shadow-[0_8px_24px_rgba(41,28,87,0.12)] sm:p-6" style={{ backgroundColor: cls.color || "#291C57" }}><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-white/65">{cls.section || "Class"}</p><h2 className="mt-1 text-xl font-bold sm:text-2xl">{cls.title}</h2><div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm text-white/85"><span>{cls.subject}</span><span>{cls.students} students</span><span>{exams.length} examinations</span></div><p className="mt-3 text-xs font-medium text-white/75">Class code: {cls.classCode}</p></section>
      <div className="mb-4"><h2 className="text-lg font-bold text-[#0B1739]">Examinations</h2><p className="text-xs text-slate-500">Examinations currently associated with this class.</p></div>
      {exams.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center text-sm text-slate-500">No examinations have been created for this class yet.</div> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{exams.map((exam) => <button key={exam.id} onClick={() => navigate(`/Professor/classes/${classId}/exams/${exam.id}`)} className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-[#291C57]/20 hover:shadow-md"><div className="flex items-start justify-between gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-xl text-[#1A73E8]"><i className="bx bxs-file" /></span><i className="bx bx-chevron-right text-xl text-slate-300 group-hover:text-[#291C57]" /></div><h3 className="mt-4 line-clamp-2 text-sm font-bold leading-5 text-[#0B1739]">{exam.title}</h3><div className="mt-3 flex items-center justify-between text-xs text-slate-500"><span>{exam.date ? new Date(`${exam.date}T00:00:00`).toLocaleDateString() : "No date"}</span><span>{exam.submissions} submissions</span></div></button>)}</div>}
    </PageShell>
  );
}

export default ClassView;
