import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getClass, getClassStudents } from "../../../api/classesApi";
import { BackButton, PageHeader, PageShell } from "../../../components/prof/PageShell";

function initials(name) { return name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase(); }

function StudentsList() {
  const { classId } = useParams();
  const navigate = useNavigate();
  const [cls, setCls] = useState(null);
  const [students, setStudents] = useState([]);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([getClass(classId), getClassStudents(classId)]).then(([classData, studentData]) => { if (active) { setCls(classData); setStudents(studentData); } }).catch((err) => { if (active) setError(err.message || "Unable to load students."); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [classId]);

  const copyCode = async () => {
    if (!cls?.classCode) return;
    try { await navigator.clipboard.writeText(cls.classCode); setCopied(true); window.setTimeout(() => setCopied(false), 1800); } catch { setError("Unable to copy the class code."); }
  };

  if (loading) return <PageShell><div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">Loading students...</div></PageShell>;
  if (error || !cls) return <PageShell><div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">{error || "Class not found."}</div></PageShell>;

  return <PageShell className="flex flex-col"><BackButton onClick={() => navigate(-1)} /><PageHeader title="Students" description={`${cls.section || ""}${cls.section ? " · " : ""}${cls.title}`} action={<span className="rounded-full bg-[#F1EFF7] px-3 py-1.5 text-xs font-bold text-[#291C57]">{students.length} students</span>} />
    <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-bold uppercase tracking-wide text-slate-400">Class code</p><p className="mt-1 font-mono text-lg font-bold tracking-wide text-[#291C57]">{cls.classCode}</p></div><button onClick={copyCode} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#291C57] px-4 py-2.5 text-sm font-bold text-[#291C57] hover:bg-[#F8F6FC]"><i className={`bx ${copied ? "bx-check" : "bx-copy"}`} />{copied ? "Copied" : "Copy code"}</button></div></section>
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="border-b border-slate-100 px-4 py-4 sm:px-5"><h2 className="font-bold text-[#0B1739]">Enrolled students</h2><p className="mt-0.5 text-xs text-slate-500">Students currently associated with this class.</p></div><div className="divide-y divide-slate-100">{students.length === 0 ? <div className="px-5 py-12 text-center text-sm text-slate-500">No students are enrolled yet.</div> : students.map((student, index) => <div key={student.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5"><span className="w-5 text-center text-xs font-bold text-slate-400">{index + 1}</span><div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#291C57] text-xs font-bold text-white">{initials(student.name)}</div><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold text-[#0B1739]">{student.name}</p><p className="truncate text-xs text-slate-500">{student.email}</p></div></div>)}</div></section>
  </PageShell>;
}

export default StudentsList;
