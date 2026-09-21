import { APP_LOGO, APP_LOGO_ALT, APP_NAME } from "../../branding";

function ProfessorTopbar({ onAdd, user }) {
  return (
    <header className="z-40 flex h-[66px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6">
      <div className="flex items-center gap-2.5">
        <img src={APP_LOGO} alt={APP_LOGO_ALT} className="h-9 w-auto object-contain sm:h-10" />
        <h1 className="text-[21px] font-bold tracking-[0.08em] text-[#462776] sm:text-2xl" style={{ fontFamily: "'Audiowide', sans-serif" }}>
          {APP_NAME}
        </h1>
      </div>

      <div className="flex items-center gap-2.5 sm:gap-3">
        <button
          onClick={onAdd}
          aria-label="Create new class"
          className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 bg-white text-[#0B1739] shadow-sm transition hover:border-[#291C57]/30 hover:bg-[#F8F6FC] hover:text-[#291C57] active:scale-95"
        >
          <i className="bx bx-plus text-2xl" />
        </button>
        <button
          aria-label="Profile"
          className="grid h-10 w-10 place-items-center overflow-hidden rounded-xl border border-slate-200 bg-slate-50 text-[#291C57] shadow-sm"
        >
          {user?.avatarUrl ? <img src={user.avatarUrl} alt="Profile" className="h-full w-full object-cover" /> : <i className="bx bxs-user text-xl" />}
        </button>
      </div>
    </header>
  );
}

export default ProfessorTopbar;
