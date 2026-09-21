import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader, PageShell } from "../../../components/prof/PageShell";
import { listSecurityLog } from "../../../api/adminApi";

const PAGE_SIZE = 25;

const EVENT_TYPES = {
  login_success: { label: "Signed in", style: "bg-emerald-50 text-emerald-700" },
  login_failed: { label: "Failed sign-in", style: "bg-rose-50 text-rose-700" },
  logout: { label: "Signed out", style: "bg-slate-100 text-slate-600" },
  password_reset: { label: "Password reset", style: "bg-amber-50 text-amber-800" },
  role_changed: { label: "Role changed", style: "bg-[#F3F0FA] text-[#291C57]" },
  user_created: { label: "Account created", style: "bg-sky-50 text-sky-700" },
  user_deleted: { label: "Account deleted", style: "bg-rose-50 text-rose-700" },
};

const FALLBACK_STYLE = "bg-slate-100 text-slate-600";
const FAILED_STYLE = "bg-rose-50 text-rose-700";

const inputClass =
  "w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[#291C57] focus:ring-4 focus:ring-[#291C57]/10";

const dateFormat = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

function prettify(type) {
  const text = String(type || "event").replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function parseTimestamp(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function relativeTime(date) {
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 0) return "in the future";
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return "";
}

function Timestamp({ value }) {
  const date = parseTimestamp(value);
  if (!date) {
    return <span className="font-mono text-xs text-slate-400">{value ? String(value) : "—"}</span>;
  }
  const relative = relativeTime(date);
  return (
    <time dateTime={date.toISOString()} title={date.toISOString()} className="block">
      <span className="block font-mono text-xs font-semibold text-slate-700">
        {dateFormat.format(date)}
      </span>
      {relative && <span className="block text-[11px] text-slate-400">{relative}</span>}
    </time>
  );
}

function AdminSecurity() {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(null);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Only the most recent request may update the table, so a slow response for
  // an old search can't overwrite a newer one.
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const result = await listSecurityLog({
        search,
        type,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      if (id !== requestId.current) return;
      setEvents(result.events || []);
      setTotal(typeof result.total === "number" ? result.total : null);
      setError("");
    } catch (err) {
      if (id !== requestId.current) return;
      setError(err.message || "Unable to load the security log.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [search, type, page]);

  // Debounced so typing in the search box doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  const hasNext =
    total !== null ? (page + 1) * PAGE_SIZE < total : events.length === PAGE_SIZE;
  const first = events.length ? page * PAGE_SIZE + 1 : 0;
  const last = page * PAGE_SIZE + events.length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="Administration"
        title="Security log"
        description={`Sign-ins and account changes, newest first. Times are shown in your timezone (${localZone}).`}
        action={
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            <i className={`bx bx-refresh text-lg ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        }
      />

      {error && (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <i className="bx bx-error-circle mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1 break-words">{error}</span>
          <button
            onClick={() => setError("")}
            aria-label="Dismiss"
            className="shrink-0 opacity-60 hover:opacity-100"
          >
            <i className="bx bx-x text-lg" />
          </button>
        </div>
      )}

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <i className="bx bx-search absolute left-3 top-1/2 -translate-y-1/2 text-lg text-slate-400" />
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            placeholder="Search by email, IP address or details"
            className={`${inputClass} pl-10`}
          />
        </div>
        <select
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            setPage(0);
          }}
          className={`${inputClass} sm:w-56`}
        >
          <option value="">All events</option>
          {Object.entries(EVENT_TYPES).map(([value, { label }]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading && events.length === 0 ? (
          <p className="px-5 py-14 text-center text-sm text-slate-500">Loading security log…</p>
        ) : events.length === 0 ? (
          <p className="px-5 py-14 text-center text-sm text-slate-500">
            {search || type ? "No events match those filters." : "No security events recorded yet."}
          </p>
        ) : (
          <div className={`overflow-x-auto transition-opacity ${loading ? "opacity-60" : ""}`}>
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-[11px] font-bold uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Event</th>
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">IP address</th>
                  <th className="px-4 py-3">Details</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e, index) => {
                  const known = EVENT_TYPES[e.type];
                  const failed = e.success === false;
                  const badgeStyle = failed ? FAILED_STYLE : known?.style || FALLBACK_STYLE;
                  return (
                    <tr
                      key={e.id ?? `${e.timestamp}-${index}`}
                      className="border-b border-slate-50 align-top last:border-0"
                    >
                      <td className="whitespace-nowrap px-4 py-3">
                        <Timestamp value={e.timestamp ?? e.createdAt} />
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold ${badgeStyle}`}
                        >
                          {known?.label || prettify(e.type)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        <span className="break-all">{e.actor || e.email || "—"}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-500">
                        {e.ip || "—"}
                      </td>
                      <td className="max-w-[280px] break-words px-4 py-3 text-xs text-slate-500">
                        {e.detail || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {events.length > 0 && (
          <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3">
            <p className="text-xs text-slate-500">
              {total !== null ? `${first}–${last} of ${total}` : `${first}–${last}`}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0 || loading}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={!hasNext || loading}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>
    </PageShell>
  );
}

export default AdminSecurity;