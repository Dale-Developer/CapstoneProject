import { useMemo, useState } from "react";
import { useEffect } from "react";
import { PageHeader, PageShell, StatCard } from "../../../components/prof/PageShell";
import { getRanking } from "../../../api/rankingApi";

const CLASS_OPTIONS = (rows) => ["All classes", ...new Set(rows.map((student) => student.className).filter(Boolean))];
const initials = (name) => name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();

function rankBadge(rank) {
  if (rank === 1) return "bg-amber-50 text-amber-700 ring-amber-200";
  if (rank === 2) return "bg-slate-100 text-slate-700 ring-slate-200";
  if (rank === 3) return "bg-orange-50 text-orange-700 ring-orange-200";
  return "bg-[#F1EFF7] text-[#291C57] ring-[#E2DBF0]";
}

function RankingRow({ student }) {
  return (
    <div className="grid grid-cols-[52px_minmax(220px,1.5fr)_minmax(160px,1fr)_90px_110px_90px] items-center gap-4 border-b border-slate-100 px-5 py-4 last:border-0 hover:bg-slate-50/70">
      <span className={`grid h-9 w-9 place-items-center rounded-full text-xs font-extrabold ring-1 ${rankBadge(student.rank)}`}>#{student.rank}</span>
      <div className="flex min-w-0 items-center gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#291C57] text-xs font-bold text-white">{initials(student.name)}</span><div className="min-w-0"><p className="truncate text-sm font-bold text-[#0B1739]">{student.name}</p><p className="truncate text-xs text-slate-400">{student.studentId}</p></div></div>
      <div className="min-w-0"><p className="truncate text-sm font-medium text-slate-700">{student.className}</p><p className="text-xs text-slate-400">{student.section}</p></div>
      <p className="text-sm font-bold text-slate-600">{student.examsCompleted}</p>
      <p className="text-sm font-extrabold text-[#291C57]">{student.average.toFixed(1)}%</p>
      <span className={`justify-self-start text-xs font-bold ${student.trend >= 0 ? "text-emerald-600" : "text-rose-600"}`}><i className={`bx ${student.trend >= 0 ? "bx-trending-up" : "bx-trending-down"} mr-1`} />{student.trend > 0 ? "+" : ""}{student.trend.toFixed(1)}%</span>
    </div>
  );
}

function MobileRankingCard({ student }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-3"><span className={`grid h-9 w-9 place-items-center rounded-full text-xs font-extrabold ring-1 ${rankBadge(student.rank)}`}>#{student.rank}</span><span className="grid h-10 w-10 place-items-center rounded-full bg-[#291C57] text-xs font-bold text-white">{initials(student.name)}</span><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold text-[#0B1739]">{student.name}</p><p className="truncate text-xs text-slate-400">{student.studentId}</p></div><p className="text-lg font-extrabold text-[#291C57]">{student.average.toFixed(1)}%</p></div>
      <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-3 text-xs"><div><p className="text-slate-400">Class</p><p className="mt-0.5 truncate font-semibold text-slate-700">{student.className}</p></div><div><p className="text-slate-400">Exams</p><p className="mt-0.5 font-semibold text-slate-700">{student.examsCompleted} completed</p></div></div>
      <div className={`mt-3 text-xs font-bold ${student.trend >= 0 ? "text-emerald-600" : "text-rose-600"}`}><i className={`bx ${student.trend >= 0 ? "bx-trending-up" : "bx-trending-down"} mr-1`} />{student.trend > 0 ? "+" : ""}{student.trend.toFixed(1)}% from previous results</div>
    </article>
  );
}

export default function Ranking() {
  const [search, setSearch] = useState("");
  const [rankingData, setRankingData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedClass, setSelectedClass] = useState("All classes");

  useEffect(() => {
    getRanking().then(setRankingData).catch((err) => setError(err.message || "Unable to load rankings.")).finally(() => setLoading(false));
  }, []);

  const rankedStudents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return rankingData.filter((student) => {
      const classMatch = selectedClass === "All classes" || student.className === selectedClass;
      const searchMatch = !query || `${student.name} ${student.studentId} ${student.section} ${student.className}`.toLowerCase().includes(query);
      return classMatch && searchMatch;
    }).sort((a, b) => b.average - a.average).map((student, index) => ({ ...student, rank: index + 1 }));
  }, [search, selectedClass, rankingData]);

  const top = rankedStudents[0];
  const average = rankedStudents.length ? rankedStudents.reduce((sum, student) => sum + student.average, 0) / rankedStudents.length : 0;
  const totalExams = rankedStudents.reduce((sum, student) => sum + student.examsCompleted, 0);

  return (
    <PageShell>
      <PageHeader eyebrow="Performance Overview" title="Student Ranking" description="Compare assessment results and identify the highest-performing students." action={<span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700 ring-1 ring-emerald-100"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />Rankings updated</span>} />

      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {loading && <div className="mb-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">Loading rankings...</div>}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Top student" value={top ? top.name : "—"} description={top ? `${top.average.toFixed(1)}% average` : "No results"} icon="bxs-trophy" iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Class average" value={`${average.toFixed(1)}%`} description="Current filtered results" icon="bx-line-chart" iconClass="bg-blue-50 text-[#1A73E8]" />
        <StatCard label="Ranked students" value={rankedStudents.length} description="Matching selected view" icon="bxs-group" />
        <StatCard label="Exams completed" value={totalExams} description="Across ranked students" icon="bxs-file" iconClass="bg-purple-50 text-purple-600" />
      </div>

      <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4">
        <div className="flex flex-col gap-3 lg:flex-row">
          <div className="relative flex-1"><i className="bx bx-search absolute left-4 top-1/2 -translate-y-1/2 text-lg text-slate-400" /><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search student, ID, class, or section" className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-11 pr-4 text-sm outline-none focus:border-[#291C57] focus:bg-white focus:ring-4 focus:ring-[#291C57]/10" /></div>
          <div className="relative lg:w-[320px]"><i className="bx bx-book-open absolute left-4 top-1/2 -translate-y-1/2 text-lg text-slate-400" /><select value={selectedClass} onChange={(e) => setSelectedClass(e.target.value)} className="w-full appearance-none rounded-xl border border-slate-200 bg-white py-2.5 pl-11 pr-10 text-sm font-semibold text-slate-700 outline-none focus:border-[#291C57] focus:ring-4 focus:ring-[#291C57]/10">{CLASS_OPTIONS(rankingData).map((name) => <option key={name}>{name}</option>)}</select><i className="bx bx-chevron-down pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-lg text-slate-400" /></div>
        </div>
      </section>

      {rankedStudents.length >= 3 && (
        <section className="mb-5"><div className="mb-3"><h2 className="text-lg font-bold text-[#0B1739]">Top Performers</h2><p className="text-xs text-slate-500">Leading students in the selected view.</p></div><div className="grid gap-3 md:grid-cols-3">
          {rankedStudents.slice(0, 3).map((student, index) => <article key={student.id} className={`rounded-2xl border p-4 shadow-sm ${index === 0 ? "border-amber-200 bg-[#FFFDF7]" : index === 1 ? "border-slate-200 bg-white" : "border-orange-200 bg-[#FFFBF8]"}`}><div className="flex items-center justify-between"><span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-wider text-slate-600 ring-1 ring-slate-200">{index + 1}{index === 0 ? "st" : index === 1 ? "nd" : "rd"} Place</span><i className={`bx ${index === 0 ? "bxs-trophy text-amber-600" : "bx-medal text-slate-500"} text-xl`} /></div><div className="mt-4 flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-full bg-[#291C57] text-xs font-bold text-white">{initials(student.name)}</span><div className="min-w-0"><p className="truncate font-bold text-[#0B1739]">{student.name}</p><p className="truncate text-xs text-slate-500">{student.section}</p></div></div><div className="mt-4 flex items-end justify-between"><div><p className="text-xs text-slate-400">Average score</p><p className="mt-0.5 text-2xl font-extrabold text-[#291C57]">{student.average.toFixed(1)}%</p></div><p className="text-xs font-medium text-slate-500">{student.examsCompleted} exams</p></div></article>)}
        </div></section>
      )}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-4 py-4 sm:px-5"><h2 className="font-bold text-[#0B1739]">Overall Ranking</h2><p className="mt-0.5 text-xs text-slate-500">Students are ordered by average examination score.</p></div>
        {rankedStudents.length === 0 ? <div className="px-6 py-16 text-center"><i className="bx bx-search-alt text-4xl text-slate-300" /><p className="mt-3 font-bold text-[#0B1739]">No students found</p><p className="mt-1 text-sm text-slate-500">Try another search or class.</p></div> : <>
          <div className="hidden overflow-x-auto lg:block"><div className="min-w-[920px]"><div className="grid grid-cols-[52px_minmax(220px,1.5fr)_minmax(160px,1fr)_90px_110px_90px] gap-4 border-b border-slate-100 bg-slate-50/70 px-5 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-400"><span>Rank</span><span>Student</span><span>Class</span><span>Exams</span><span>Average</span><span>Trend</span></div>{rankedStudents.map((student) => <RankingRow key={student.id} student={student} />)}</div></div>
          <div className="grid gap-3 p-3 lg:hidden">{rankedStudents.map((student) => <MobileRankingCard key={student.id} student={student} />)}</div>
        </>}
      </section>
    </PageShell>
  );
}
