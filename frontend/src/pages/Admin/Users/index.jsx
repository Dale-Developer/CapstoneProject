import { useCallback, useEffect, useState } from "react";
import { PageHeader, PageShell, StatCard } from "../../../components/prof/PageShell";
import {
  changeUserRole,
  createUser,
  deleteUser,
  getAdminOverview,
  listUsers,
  resetUserPassword,
} from "../../../api/adminApi";
import { getStoredUser } from "../../../api/session";

const ROLE_STYLE = {
  admin: "bg-[#F3F0FA] text-[#291C57]",
  teacher: "bg-sky-50 text-sky-700",
  student: "bg-slate-100 text-slate-600",
};
const ROLE_LABEL = { admin: "Admin", teacher: "Professor", student: "Student" };

function Banner({ tone, message, onDismiss }) {
  if (!message) return null;
  const styles = {
    error: "border-rose-200 bg-rose-50 text-rose-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  }[tone];
  return (
    <div className={`mb-5 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${styles}`}>
      <i className={`bx ${tone === "error" ? "bx-error-circle" : "bx-check-circle"} mt-0.5 shrink-0`} />
      <span className="min-w-0 flex-1 break-words">{message}</span>
      <button onClick={onDismiss} aria-label="Dismiss" className="shrink-0 opacity-60 hover:opacity-100">
        <i className="bx bx-x text-lg" />
      </button>
    </div>
  );
}

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4">
      <div className="max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:max-w-md sm:rounded-2xl">
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 className="text-lg font-bold text-[#0B1739]">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-600">
            <i className="bx bx-x text-2xl" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[#291C57] focus:ring-4 focus:ring-[#291C57]/10";

function AdminUsers() {
  const me = getStoredUser();
  const [users, setUsers] = useState([]);
  const [overview, setOverview] = useState(null);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    firstName: "", lastName: "", email: "", password: "", role: "teacher",
  });
  const [resetting, setResetting] = useState(null);
  const [newPassword, setNewPassword] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, stats] = await Promise.all([
        listUsers({ search, role: roleFilter }),
        getAdminOverview(),
      ]);
      setUsers(list.users || []);
      setOverview(stats);
    } catch (err) {
      setError(err.message || "Unable to load users.");
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter]);

  // Debounced so typing in the search box doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  const act = async (fn, onDone) => {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await fn();
      setSuccess(result?.message || "Done.");
      onDone?.();
      await load();
    } catch (err) {
      setError(err.message || "That didn't work.");
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = () =>
    act(() => createUser(form), () => {
      setCreating(false);
      setForm({ firstName: "", lastName: "", email: "", password: "", role: "teacher" });
    });

  const handleReset = () =>
    act(() => resetUserPassword(resetting.id, newPassword), () => {
      setResetting(null);
      setNewPassword("");
    });

  const handleRole = (user, role) => {
    if (role === user.role) return;
    if (!window.confirm(`Change ${user.email} from ${ROLE_LABEL[user.role]} to ${ROLE_LABEL[role]}?`)) return;
    act(() => changeUserRole(user.id, role));
  };

  const handleDelete = (user) => {
    // Typing the email is deliberate friction: deletion cascades to their
    // submissions and cannot be undone from the interface.
    const typed = window.prompt(
      `Deleting ${user.email} also removes their submissions. This cannot be undone.\n\nType the email to confirm:`
    );
    if (typed?.trim() !== user.email) return;
    act(() => deleteUser(user.id));
  };

  return (
    <PageShell>
      <PageHeader
        eyebrow="Administration"
        title="User accounts"
        description="Create accounts, change roles, reset passwords and remove users."
        action={
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-[#291C57] px-4 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-[#211645]"
          >
            <i className="bx bx-plus text-lg" />
            New account
          </button>
        }
      />

      <Banner tone="error" message={error} onDismiss={() => setError("")} />
      <Banner tone="success" message={success} onDismiss={() => setSuccess("")} />

      {overview && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Total users" value={overview.users.total} icon="bx-group"
            description={`${overview.users.newThisWeek} joined this week`} />
          <StatCard label="Professors" value={overview.users.professors} icon="bx-chalkboard" />
          <StatCard label="Students" value={overview.users.students} icon="bx-user" />
          <StatCard label="Administrators" value={overview.users.admins} icon="bx-shield-quarter" />
        </div>
      )}

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <i className="bx bx-search absolute left-3 top-1/2 -translate-y-1/2 text-lg text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or email"
            className={`${inputClass} pl-10`}
          />
        </div>
        <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}
          className={`${inputClass} sm:w-48`}>
          <option value="">All roles</option>
          <option value="admin">Administrators</option>
          <option value="teacher">Professors</option>
          <option value="student">Students</option>
        </select>
      </div>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <p className="px-5 py-14 text-center text-sm text-slate-500">Loading accounts…</p>
        ) : users.length === 0 ? (
          <p className="px-5 py-14 text-center text-sm text-slate-500">
            No accounts match that search.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-[11px] font-bold uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="px-4 py-3">Activity</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = me?.email === u.email;
                  return (
                    <tr key={u.id} className="border-b border-slate-50 last:border-0">
                      <td className="px-4 py-3 font-semibold text-slate-700">
                        {u.name}
                        {isSelf && (
                          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">
                            you
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-500">{u.email}</td>
                      <td className="px-4 py-3">
                        <select
                          value={u.role}
                          disabled={isSelf || busy}
                          onChange={(e) => handleRole(u, e.target.value)}
                          title={isSelf ? "You cannot change your own role." : undefined}
                          className={`rounded-full px-2.5 py-1 text-[11px] font-bold disabled:cursor-not-allowed disabled:opacity-60 ${ROLE_STYLE[u.role]}`}
                        >
                          <option value="admin">Admin</option>
                          <option value="teacher">Professor</option>
                          <option value="student">Student</option>
                        </select>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">
                        {u.role === "teacher"
                          ? `${u.classesTaught} class${u.classesTaught === 1 ? "" : "es"}`
                          : u.role === "student"
                          ? `${u.classesEnrolled} enrolled · ${u.submissions} submitted`
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button
                            onClick={() => { setResetting(u); setNewPassword(""); }}
                            disabled={busy}
                            title="Reset password"
                            className="grid h-8 w-8 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-[#291C57] disabled:opacity-40"
                          >
                            <i className="bx bx-key text-lg" />
                          </button>
                          <button
                            onClick={() => handleDelete(u)}
                            disabled={isSelf || busy}
                            title={isSelf ? "You cannot delete your own account." : "Delete"}
                            className="grid h-8 w-8 place-items-center rounded-lg text-slate-500 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-30"
                          >
                            <i className="bx bx-trash text-lg" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {creating && (
        <Modal title="Create an account" onClose={() => setCreating(false)}>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input placeholder="First name" value={form.firstName} className={inputClass}
                onChange={(e) => setForm({ ...form, firstName: e.target.value })} />
              <input placeholder="Last name" value={form.lastName} className={inputClass}
                onChange={(e) => setForm({ ...form, lastName: e.target.value })} />
            </div>
            <input type="email" placeholder="Email" value={form.email} className={inputClass}
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <input type="password" placeholder="Password (at least 8 characters)"
              value={form.password} className={inputClass}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <select value={form.role} className={inputClass}
              onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="teacher">Professor</option>
              <option value="student">Student</option>
              <option value="admin">Administrator</option>
            </select>
            {form.role === "admin" && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-4 text-amber-800">
                An administrator can create, demote and delete any account, including yours.
              </p>
            )}
            <button
              onClick={handleCreate}
              disabled={busy || !form.email || form.password.length < 8 || !form.firstName || !form.lastName}
              className="w-full rounded-xl bg-[#291C57] px-4 py-3 text-sm font-bold text-white hover:bg-[#211645] disabled:opacity-40"
            >
              {busy ? "Creating…" : "Create account"}
            </button>
          </div>
        </Modal>
      )}

      {resetting && (
        <Modal title={`Reset password`} onClose={() => setResetting(null)}>
          <p className="mb-3 text-sm text-slate-500">
            Setting a new password for <span className="font-semibold text-slate-700">{resetting.email}</span>.
            They are not notified, so tell them yourself.
          </p>
          <input type="password" placeholder="New password (at least 8 characters)"
            value={newPassword} className={inputClass}
            onChange={(e) => setNewPassword(e.target.value)} />
          <button
            onClick={handleReset}
            disabled={busy || newPassword.length < 8}
            className="mt-3 w-full rounded-xl bg-[#291C57] px-4 py-3 text-sm font-bold text-white hover:bg-[#211645] disabled:opacity-40"
          >
            {busy ? "Saving…" : "Reset password"}
          </button>
        </Modal>
      )}
    </PageShell>
  );
}

export default AdminUsers;
