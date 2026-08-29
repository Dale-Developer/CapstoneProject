import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getClasses } from "../../../api/classesApi";
import { PageHeader, PageShell } from "../../../components/prof/PageShell";

function ClassCard({ cls, onOpen }) {
  return (
    <article className="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_5px_18px_rgba(15,23,42,0.05)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_26px_rgba(15,23,42,0.09)]">
      <div className="relative h-[112px] px-4 py-4 text-white" style={{ backgroundColor: cls.color || "#291C57" }}>
        <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-[10px] font-bold uppercase tracking-wider text-white/75">{cls.section || "No section"}</p><h2 className="mt-1 line-clamp-2 text-[15px] font-bold leading-5">{cls.title}</h2><p className="mt-1 text-xs font-medium text-white/80">{cls.subject}</p></div><span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/10 ring-1 ring-white/15"><i className="bx bx-book-open text-lg" /></span></div>
      </div>
      <div className="flex items-center justify-between gap-3 px-4 py-3.5"><div className="flex items-center gap-3 text-xs font-medium text-slate-500"><span className="flex items-center gap-1.5"><i className="bx bxs-group text-[#291C57]" />{cls.students} Students</span><span className="flex items-center gap-1.5"><i className="bx bx-file text-[#291C57]" />{cls.exams} Exams</span></div><button onClick={() => onOpen(cls.id)} className="shrink-0 rounded-lg border border-[#291C57] px-3.5 py-1.5 text-xs font-bold text-[#291C57] transition hover:bg-[#291C57] hover:text-white">Open</button></div>
    </article>
  );
}

function Dashboard() {
  const navigate = useNavigate();
  const [classes, setClasses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadClasses = useCallback(async () => {
    setLoading(true); setError("");
    try { setClasses(await getClasses()); }
    catch (err) { setError(err.message || "Unable to load classes."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    loadClasses();
    const refresh = () => loadClasses();
    window.addEventListener("esscan:classes-changed", refresh);
    return () => window.removeEventListener("esscan:classes-changed", refresh);
  }, [loadClasses]);

  return (
    <PageShell>
      <PageHeader title="Your Classes" description="Manage your classes, examinations, and student submissions." action={<span className="w-fit rounded-full bg-[#F1EFF7] px-3 py-1.5 text-xs font-bold text-[#291C57]">{classes.length} Classes</span>} />
      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
      {loading ? <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading your classes...</div> : classes.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center"><i className="bx bx-book-add text-3xl text-[#291C57]" /><h2 className="mt-3 font-bold text-[#0B1739]">No classes yet</h2><p className="mt-1 text-sm text-slate-500">Use the + button above to create your first class.</p></div> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{classes.map((cls) => <ClassCard key={cls.id} cls={cls} onOpen={(id) => navigate(`/Professor/dashboard/class/${id}`)} />)}</div>}
    </PageShell>
  );
}

export default Dashboard;
