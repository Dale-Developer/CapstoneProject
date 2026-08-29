
export function PageShell({ children, className = "" }) {
  return (
    <div
      className={`mx-auto w-full max-w-[1600px] px-4 py-5 pb-24 sm:px-5 md:px-6 md:py-6 md:pb-8 lg:px-8 ${className}`}
    >
      {children}
    </div>
  );
}

export function PageHeader({ eyebrow, title, description, action }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:mb-7 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-[#4C3A99]">
            {eyebrow}
          </p>
        )}
        <h1 className="text-2xl font-bold tracking-tight text-[#0B1739] sm:text-3xl">
          {title}
        </h1>
        {description && (
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function BackButton({ onClick, label = "Back" }) {
  return (
    <button
      onClick={onClick}
      className="mb-5 inline-flex items-center gap-1.5 rounded-lg px-1 py-1 text-sm font-medium text-slate-500 transition hover:text-[#291C57] focus:outline-none focus:ring-4 focus:ring-[#291C57]/10"
    >
      <i className="bx bx-chevron-left text-lg" />
      {label}
    </button>
  );
}

export function StatCard({ label, value, description, icon, iconClass = "text-[#291C57] bg-[#F3F0FA]" }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_4px_18px_rgba(15,23,42,0.04)] sm:p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">{label}</p>
          <p className="mt-2 text-2xl font-extrabold tracking-tight text-[#0B1739]">{value}</p>
          {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
        </div>
        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-xl ${iconClass}`}>
          <i className={`bx ${icon}`} />
        </span>
      </div>
    </div>
  );
}

export function StatusBadge({ status }) {
  // These are the exact strings SubmissionStatus (backend) can produce.
  // The map previously only covered "Submitted / Processing / Flagged /
  // Pending" — none of which the API actually returns except Pending — so
  // every badge silently fell back to the same gray "Pending" style
  // regardless of the real status. Failed in particular needs to stand out.
  const styles = {
    Pending: "bg-slate-100 text-slate-600 ring-slate-200",
    Uploaded: "bg-amber-50 text-amber-700 ring-amber-100",
    OCR_Processing: "bg-amber-50 text-amber-700 ring-amber-100",
    OCR_Completed: "bg-amber-50 text-amber-700 ring-amber-100",
    NLP_Processing: "bg-amber-50 text-amber-700 ring-amber-100",
    Graded: "bg-[#F1EFF7] text-[#291C57] ring-[#E4DEF3]",
    Released: "bg-emerald-50 text-emerald-700 ring-emerald-100",
    Failed: "bg-rose-50 text-rose-700 ring-rose-100",
  };
  const labels = {
    OCR_Processing: "Processing",
    OCR_Completed: "Processing",
    NLP_Processing: "Grading",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ring-1 ${styles[status] || styles.Pending}`}>
      <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current" />
      {labels[status] || status}
    </span>
  );
}
