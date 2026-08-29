import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getClasses, joinClass } from "../../api/classesApi";
import { PageHeader, PageShell } from "../../components/prof/PageShell";

function ClassCard({ cls, onOpen }) {
  return <article className="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_5px_18px_rgba(15,23,42,0.05)] transition hover:-translate-y-0.5 hover:shadow-md">
    <div className="relative h-[112px] px-4 py-4 text-white" style={{ backgroundColor: cls.color || "#291C57" }}>
      <p className="text-[10px] font-bold uppercase tracking-wider text-white/75">{cls.section || "Class"}</p>
      <h2 className="mt-1 line-clamp-2 text-[15px] font-bold leading-5">{cls.title}</h2>
      <p className="mt-1 text-xs font-medium text-white/80">{cls.subject}</p>
    </div>
    <div className="flex items-center justify-between gap-3 px-4 py-3.5">
      <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500"><i className="bx bx-file text-[#291C57]" />{cls.exams} Exams</span>
      <button onClick={() => onOpen(cls.id)} className="rounded-lg border border-[#291C57] px-3.5 py-1.5 text-xs font-bold text-[#291C57] hover:bg-[#291C57] hover:text-white">Open</button>
    </div>
  </article>;
}

export default function StudentDashboard() {
  const navigate = useNavigate();
  const [classes, setClasses] = useState([]);
  const [code, setCode] = useState("");
  const [joinOpen, setJoinOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState("");

  const load = async () => { setLoading(true); setError(""); try { setClasses(await getClasses()); } catch (e) { setError(e.message || "Unable to load classes."); } finally { setLoading(false); } };
  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault(); if (!code.trim()) return;
    setJoining(true); setError("");
    try { await joinClass(code.trim()); setCode(""); setJoinOpen(false); await load(); }
    catch (e) { setError(e.message || "Unable to join class."); }
    finally { setJoining(false); }
  };

  return <PageShell>
    <PageHeader title="Your Classes" description="View your classes and the examinations assigned to you." action={<button onClick={() => setJoinOpen(true)} className="inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-[#211645]"><i className="bx bx-plus" />Join class</button>} />
    {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
    {loading ? <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading your classes...</div> : classes.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center"><i className="bx bx-book-add text-3xl text-[#291C57]" /><h2 className="mt-3 font-bold text-[#0B1739]">No classes yet</h2><p className="mt-1 text-sm text-slate-500">Join a class using the code provided by your professor.</p></div> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{classes.map(c => <ClassCard key={c.id} cls={c} onOpen={(id) => navigate(`/student/class/${id}`)} />)}</div>}
    {joinOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"><form onSubmit={submit} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"><div className="flex items-start justify-between"><div><h2 className="text-lg font-bold text-[#0B1739]">Join class</h2><p className="mt-1 text-sm text-slate-500">Enter the class code from your professor.</p></div><button type="button" onClick={() => setJoinOpen(false)} className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-100"><i className="bx bx-x text-xl" /></button></div><input autoFocus value={code} onChange={e => setCode(e.target.value)} placeholder="Class code" className="mt-5 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-[#291C57] focus:ring-4 focus:ring-[#291C57]/10" /><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setJoinOpen(false)} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-bold text-slate-600">Cancel</button><button disabled={joining} className="rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50">{joining ? "Joining..." : "Join class"}</button></div></form></div>}
  </PageShell>;
}
