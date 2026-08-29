import { useEffect, useState } from "react";
import { getProfile, updatePassword, updateProfile } from "../../../api/profileApi";
import { clearSession } from "../../../api/session";

/**
 * Icon helper
 * -----------
 * This project uses Boxicons (the `bx` classes you already see in
 * Dashboard.jsx, e.g. `bx bxs-group`) rather than lucide-react, which
 * isn't installed here. Boxicons is loaded globally via its CSS
 * (typically a <link> tag in index.html, or `import 'boxicons/css/boxicons.min.css'`
 * once in your app entry point) — no per-file import needed.
 *
 * If Boxicons isn't wired up yet, add the CDN link to your
 * index.html <head>:
 *   <link href="https://unpkg.com/boxicons@2.1.4/css/boxicons.min.css" rel="stylesheet" />
 * or install it locally: npm install boxicons
 */
function Icon({ name, size = 18, className = "" }) {
  return (
    <i
      className={`bx ${name} ${className}`}
      style={{ fontSize: size, lineHeight: 1 }}
    />
  );
}

/**
 * Profile & Settings screen
 * -------------------------
 * Single-file, self-contained React component. Each row on the main
 * screen ("Edit personal information", "Change password", "Log out",
 * "How does it work?", "Terms of Service", "Privacy Policy") opens a
 * real, working screen or dialog rather than a static placeholder.
 *
 * No topbar/bottom nav here — this is meant to be dropped inside an
 * existing app shell (e.g. as the <main> content of a layout that
 * already owns navigation). Responsive from mobile up through wide
 * desktop via a centered, max-width container.
 *
 * Views are managed with a simple string-based router (`view` state)
 * since this is a small, self-contained flow — no need for a routing
 * library here.
 */

const ACCENT = "#4C3A99";

export default function Settings() {
  const [view, setView] = useState("main"); // main | editInfo | changePassword | howItWorks | terms | privacy
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [loggedOut, setLoggedOut] = useState(false);
  const [toast, setToast] = useState(null);

  const [profile, setProfile] = useState({ firstName: "", lastName: "", email: "" });
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [profileError, setProfileError] = useState("");

  useEffect(() => {
    getProfile()
      .then((user) => setProfile({ firstName: user.first_name, lastName: user.last_name, email: user.email }))
      .catch((err) => setProfileError(err.message || "Unable to load your profile."))
      .finally(() => setLoadingProfile(false));
  }, []);

  const showToast = (message) => {
    setToast(message);
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(null), 2200);
  };

  const goTo = (v) => setView(v);
  const goBack = () => setView("main");

  if (loggedOut) {
    return <LoggedOutScreen onLogin={() => setLoggedOut(false)} />;
  }

  return (
    <div
      style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
      className="w-full min-h-full bg-transparent relative"
    >
      {/* Increased max-width from max-w-2xl to max-w-4xl for better desktop spacing */}
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
        {loadingProfile ? (
          <div className="bg-white rounded-2xl border border-slate-200/80 px-5 py-10 text-center text-sm text-slate-500">Loading profile...</div>
        ) : profileError ? (
          <div className="bg-rose-50 rounded-2xl border border-rose-100 px-5 py-4 text-sm text-rose-700">{profileError}</div>
        ) : view === "main" ? (
          <MainScreen
            profile={profile}
            onEditInfo={() => goTo("editInfo")}
            onChangePassword={() => goTo("changePassword")}
            onLogout={() => setShowLogoutConfirm(true)}
            onHowItWorks={() => goTo("howItWorks")}
            onTerms={() => goTo("terms")}
            onPrivacy={() => goTo("privacy")}
          />
        ) : view === "editInfo" ? (
          <EditPersonalInfo
            profile={profile}
            onBack={goBack}
            onSave={async (next) => {
              try {
                const saved = await updateProfile(next);
                const nextProfile = { firstName: saved.first_name, lastName: saved.last_name, email: saved.email };
                setProfile(nextProfile);
                localStorage.setItem("esscan_user", JSON.stringify(saved));
                showToast("Personal information saved");
                goBack();
              } catch (err) {
                showToast(err.message || "Unable to save personal information");
              }
            }}
          />
        ) : view === "changePassword" ? (
          <ChangePassword
            onBack={goBack}
            onSave={async (payload) => {
              try {
                await updatePassword(payload);
                showToast("Password updated");
                goBack();
              } catch (err) {
                showToast(err.message || "Unable to update password");
              }
            }}
          />
        ) : view === "howItWorks" ? (
          <HowItWorks onBack={goBack} />
        ) : view === "terms" ? (
          <TermsOfService onBack={goBack} />
        ) : view === "privacy" ? (
          <PrivacyPolicy onBack={goBack} />
        ) : null}
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-30 bg-slate-900 text-white text-sm font-medium px-4 py-2 rounded-full shadow-lg flex items-center gap-2">
          <Icon name="bx-check" size={14} className="text-emerald-400" />
          {toast}
        </div>
      )}

      {/* Logout confirmation dialog */}
      {showLogoutConfirm && (
        <LogoutConfirm
          onCancel={() => setShowLogoutConfirm(false)}
          onConfirm={() => {
            setShowLogoutConfirm(false);
            clearSession();
            window.location.href = "/";
          }}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main menu screen                                                     */
/* ------------------------------------------------------------------ */

function MainScreen({
  profile,
  onEditInfo,
  onChangePassword,
  onLogout,
  onHowItWorks,
  onTerms,
  onPrivacy,
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5 md:gap-6 md:items-start">
      {/* First column – unchanged */}
      <div>
        <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden">
          <div className="flex items-center gap-3 px-4 py-4">
            <div className="w-11 h-11 rounded-full bg-indigo-100 flex items-center justify-center shrink-0">
              <Icon name="bxs-user-circle" size={22} className="text-indigo-600" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-slate-900 leading-tight truncate">
                {profile.firstName}, {profile.lastName}
              </p>
              <p className="text-sm text-slate-400 truncate">{profile.email}</p>
            </div>
          </div>
          <Row icon={<Icon name="bx-edit-alt" size={18} />} label="Edit personal information" onClick={onEditInfo} />
          <Row icon={<Icon name="bx-lock-alt" size={18} />} label="Change password" onClick={onChangePassword} />
          <Row icon={<Icon name="bx-log-out" size={18} />} label="Log out" onClick={onLogout} last />
        </div>
      </div>

      {/* Second column – heading moved inside the card to align with the first column */}
      <div>
        <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden">
          {/* Header row – acts like a section title */}
          <div className="px-4 py-3 bg-slate-50/60 border-b border-slate-100">
            <p className="text-xs font-semibold text-slate-400 tracking-wide">
              Help &amp; Feedback
            </p>
          </div>
          <Row icon={<Icon name="bx-help-circle" size={18} />} label="How does it work?" onClick={onHowItWorks} />
          <Row icon={<Icon name="bx-file" size={18} />} label="Terms of Service" onClick={onTerms} />
          <Row icon={<Icon name="bx-shield-quarter" size={18} />} label="Privacy Policy" onClick={onPrivacy} last />
        </div>
      </div>
    </div>
  );
}

function Row({ icon, label, onClick, last }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-slate-50 active:bg-slate-100 transition-colors ${
        !last ? "border-b border-slate-100" : ""
      }`}
    >
      <span className="text-slate-700">{icon}</span>
      <span className="flex-1 text-[15px] font-medium text-slate-800">{label}</span>
      <Icon name="bx-chevron-right" size={18} className="text-slate-300" />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Shared sub-screen header                                            */
/* ------------------------------------------------------------------ */

function SubHeader({ title, onBack }) {
  return (
    <div className="flex items-center gap-3 pb-4">
      <button
        onClick={onBack}
        aria-label="Go back"
        className="w-9 h-9 rounded-full bg-white border border-slate-200 flex items-center justify-center active:scale-95 transition-transform"
      >
        <Icon name="bx-arrow-back" size={17} className="text-slate-700" />
      </button>
      <h1 className="text-[17px] font-semibold text-slate-900">{title}</h1>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Edit personal information                                            */
/* ------------------------------------------------------------------ */

function EditPersonalInfo({ profile, onBack, onSave }) {
  const [form, setForm] = useState(profile);
  const [errors, setErrors] = useState({});

  const validate = () => {
    const e = {};
    if (!form.firstName.trim()) e.firstName = "First name is required";
    if (!form.lastName.trim()) e.lastName = "Last name is required";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) e.email = "Enter a valid email";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = (ev) => {
    ev.preventDefault();
    if (validate()) onSave(form);
  };

  return (
    <div className="max-w-md">
      <SubHeader title="Edit personal information" onBack={onBack} />

      <form onSubmit={submit} className="bg-white rounded-2xl border border-slate-200/80 p-4 sm:p-5 space-y-4">
        <Field
          label="First name"
          value={form.firstName}
          onChange={(v) => setForm({ ...form, firstName: v })}
          error={errors.firstName}
        />
        <Field
          label="Last name"
          value={form.lastName}
          onChange={(v) => setForm({ ...form, lastName: v })}
          error={errors.lastName}
        />
        <Field
          label="Email address"
          type="email"
          value={form.email}
          onChange={(v) => setForm({ ...form, email: v })}
          error={errors.email}
        />

        <button
          type="submit"
          className="w-full sm:w-auto px-6 mt-2 py-3 rounded-xl text-white font-semibold text-[15px] active:scale-[0.99] transition-transform"
          style={{ backgroundColor: ACCENT }}
        >
          Save changes
        </button>
      </form>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", error }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-slate-500">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1.5 w-full rounded-xl border px-3.5 py-2.5 text-[15px] text-slate-900 outline-none focus:ring-2 transition-shadow ${
          error
            ? "border-red-300 focus:ring-red-100"
            : "border-slate-200 focus:ring-indigo-100 focus:border-indigo-300"
        }`}
      />
      {error && <span className="mt-1 block text-xs text-red-500">{error}</span>}
    </label>
  );
}

/* ------------------------------------------------------------------ */
/* Change password                                                      */
/* ------------------------------------------------------------------ */

function ChangePassword({ onBack, onSave }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState({ current: false, next: false, confirm: false });
  const [errors, setErrors] = useState({});

  const rules = [
    { test: (v) => v.length >= 8, label: "At least 8 characters" },
    { test: (v) => /[A-Z]/.test(v), label: "One uppercase letter" },
    { test: (v) => /[0-9]/.test(v), label: "One number" },
  ];

  const validate = () => {
    const e = {};
    if (!current) e.current = "Enter your current password";
    if (!rules.every((r) => r.test(next))) e.next = "Password does not meet the requirements";
    if (confirm !== next || !confirm) e.confirm = "Passwords do not match";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = (ev) => {
    ev.preventDefault();
    if (validate()) onSave({ currentPassword: current, newPassword: next });
  };

  const toggle = (field) => setShow((s) => ({ ...s, [field]: !s[field] }));

  return (
    <div className="max-w-md">
      <SubHeader title="Change password" onBack={onBack} />

      <form onSubmit={submit} className="bg-white rounded-2xl border border-slate-200/80 p-4 sm:p-5 space-y-4">
        <PasswordField
          label="Current password"
          value={current}
          onChange={setCurrent}
          visible={show.current}
          onToggle={() => toggle("current")}
          error={errors.current}
        />
        <PasswordField
          label="New password"
          value={next}
          onChange={setNext}
          visible={show.next}
          onToggle={() => toggle("next")}
          error={errors.next}
        />
        <PasswordField
          label="Confirm new password"
          value={confirm}
          onChange={setConfirm}
          visible={show.confirm}
          onToggle={() => toggle("confirm")}
          error={errors.confirm}
        />

        <ul className="space-y-1.5 pt-1">
          {rules.map((r) => {
            const passed = r.test(next);
            return (
              <li key={r.label} className="flex items-center gap-2 text-xs">
                {passed ? (
                  <Icon name="bx-check" size={13} className="text-emerald-500" />
                ) : (
                  <Icon name="bx-x" size={13} className="text-slate-300" />
                )}
                <span className={passed ? "text-slate-600" : "text-slate-400"}>{r.label}</span>
              </li>
            );
          })}
        </ul>

        <button
          type="submit"
          className="w-full sm:w-auto px-6 mt-2 py-3 rounded-xl text-white font-semibold text-[15px] active:scale-[0.99] transition-transform"
          style={{ backgroundColor: ACCENT }}
        >
          Update password
        </button>
      </form>
    </div>
  );
}

function PasswordField({ label, value, onChange, visible, onToggle, error }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-slate-500">{label}</span>
      <div className="relative mt-1.5">
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full rounded-xl border px-3.5 py-2.5 pr-10 text-[15px] text-slate-900 outline-none focus:ring-2 transition-shadow ${
            error
              ? "border-red-300 focus:ring-red-100"
              : "border-slate-200 focus:ring-indigo-100 focus:border-indigo-300"
          }`}
        />
        <button
          type="button"
          onClick={onToggle}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? <Icon name="bx-hide" size={17} /> : <Icon name="bx-show" size={17} />}
        </button>
      </div>
      {error && <span className="mt-1 block text-xs text-red-500">{error}</span>}
    </label>
  );
}

/* ------------------------------------------------------------------ */
/* Logout confirmation                                                  */
/* ------------------------------------------------------------------ */

function LogoutConfirm({ onCancel, onConfirm }) {
  return (
    <div className="fixed inset-0 z-40 bg-black/40 flex items-end sm:items-center justify-center px-0 sm:px-4">
      <div className="bg-white w-full sm:max-w-xs sm:rounded-2xl rounded-t-2xl p-5 space-y-4">
        <div className="w-11 h-11 rounded-full bg-red-50 flex items-center justify-center">
          <Icon name="bx-log-out" size={20} className="text-red-500" />
        </div>
        <div>
          <p className="font-semibold text-slate-900">Log out of your account?</p>
          <p className="text-sm text-slate-500 mt-1">
            You'll need to sign back in to access your profile and saved data.
          </p>
        </div>
        <div className="flex gap-3 pt-1">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl border border-slate-200 font-medium text-[15px] text-slate-700"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 py-2.5 rounded-xl bg-red-500 text-white font-semibold text-[15px]"
          >
            Log out
          </button>
        </div>
      </div>
    </div>
  );
}

function LoggedOutScreen({ onLogin }) {
  return (
    <div className="w-full min-h-full bg-transparent flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
      <div className="w-14 h-14 rounded-full bg-indigo-100 flex items-center justify-center">
        <Icon name="bxs-user-circle" size={26} className="text-indigo-600" />
      </div>
      <p className="font-semibold text-slate-900">You've been logged out</p>
      <p className="text-sm text-slate-500 -mt-2">Sign back in to pick up where you left off.</p>
      <button
        onClick={onLogin}
        className="mt-2 px-6 py-2.5 rounded-xl text-white font-semibold text-[15px]"
        style={{ backgroundColor: ACCENT }}
      >
        Log back in
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* How does it work? (FAQ accordion)                                   */
/* ------------------------------------------------------------------ */

function HowItWorks({ onBack }) {
  const faqs = [
    {
      q: "How do I get started?",
      a: "Create your profile, add your basic details, and you're ready to go. Everything you set up here can be changed later from this same screen.",
    },
    {
      q: "Can I change my information later?",
      a: "Yes. Open Edit personal information at any time to update your name or email address.",
    },
    {
      q: "Is my data kept private?",
      a: "Your details are only used to run your account. See the Privacy Policy for the full breakdown.",
    },
    {
      q: "What happens when I log out?",
      a: "You're signed out of this device only. Your data stays saved, and you can log back in any time.",
    },
  ];
  const [open, setOpen] = useState(0);

  return (
    <div className="max-w-xl">
      <SubHeader title="How does it work?" onBack={onBack} />
      <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden">
        {faqs.map((f, i) => (
          <div key={f.q} className={i !== faqs.length - 1 ? "border-b border-slate-100" : ""}>
            <button
              onClick={() => setOpen(open === i ? -1 : i)}
              className="w-full flex items-center justify-between gap-3 px-4 py-3.5 text-left"
            >
              <span className="text-[15px] font-medium text-slate-800">{f.q}</span>
              <Icon
                name="bx-chevron-right"
                size={16}
                className={`text-slate-400 transition-transform shrink-0 ${
                  open === i ? "rotate-90" : ""
                }`}
              />
            </button>
            {open === i && (
              <p className="px-4 pb-4 text-sm text-slate-500 leading-relaxed">{f.a}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Terms of Service / Privacy Policy (static text screens)             */
/* ------------------------------------------------------------------ */

function LegalScreen({ title, onBack, sections }) {
  return (
    <div className="max-w-xl">
      <SubHeader title={title} onBack={onBack} />
      <div className="bg-white rounded-2xl border border-slate-200/80 p-4 sm:p-5 space-y-4">
        {sections.map((s) => (
          <div key={s.heading}>
            <h2 className="text-sm font-semibold text-slate-800 mb-1">{s.heading}</h2>
            <p className="text-sm text-slate-500 leading-relaxed">{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function TermsOfService({ onBack }) {
  return (
    <LegalScreen
      title="Terms of Service"
      onBack={onBack}
      sections={[
        {
          heading: "Using your account",
          body: "You're responsible for keeping your login details secure and for the activity that happens under your account.",
        },
        {
          heading: "Acceptable use",
          body: "Use the app for its intended purpose only, and don't attempt to disrupt the service or access data that isn't yours.",
        },
        {
          heading: "Changes to the service",
          body: "Features may be added, changed, or removed over time. We'll let you know about updates that affect how you use your account.",
        },
      ]}
    />
  );
}

function PrivacyPolicy({ onBack }) {
  return (
    <LegalScreen
      title="Privacy Policy"
      onBack={onBack}
      sections={[
        {
          heading: "What we collect",
          body: "Your name, email address, and the settings you choose in this app, so we can run your account and keep it secure.",
        },
        {
          heading: "How we use it",
          body: "Only to operate the app: signing you in, saving your preferences, and getting in touch about your account.",
        },
        {
          heading: "Your controls",
          body: "You can review or update your details from Edit personal information at any time, or log out to end your session on this device.",
        },
      ]}
    />
  );
}