import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { label: "Dashboard", to: "/Professor/dashboard", icon: "bxs-dashboard" },
  { label: "Exams", to: "/Professor/exams", icon: "bx-file" },
  { label: "Upload", to: "/Professor/upload", icon: "bx-scan" },
  { label: "Ranking", to: "/Professor/ranking", icon: "bx-trophy" },
  { label: "Settings", to: "/Professor/settings", icon: "bxs-cog" },
];

function navClass({ isActive }) {
  return [
    "group flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold",
    "transition-all duration-200",
    isActive
      ? "bg-[#291C57] text-white shadow-[0_8px_18px_rgba(41,28,87,0.18)]"
      : "text-[#0B1739] hover:bg-[#f0eff5] hover:text-[#291C57]",
  ].join(" ");
}

function ProfessorSidebar({ onLogout }) {
  return (
    <>
      <aside className="hidden w-[216px] shrink-0 border-r border-[#e4e6ed] bg-white md:flex md:min-h-[calc(100dvh-65px)] md:flex-col">
        <nav className="flex flex-1 flex-col gap-1 px-2 py-5">
          {NAV_ITEMS.map(({ label, to, icon }) => (
            <NavLink key={to} to={to} className={navClass}>
              {({ isActive }) => (
                <>
                  <i
                    className={`bx ${icon} text-[20px] ${
                      isActive ? "text-white" : "text-[#0B1739]"
                    }`}
                  />
                  <span>{label.toUpperCase()}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <button
          onClick={onLogout}
          className="mx-2 mb-5 flex items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-semibold text-[#0B1739] transition hover:bg-[#f0eff5] hover:text-[#291C57]"
        >
          <i className="bx bx-log-out text-[20px]" />
          LOGOUT
        </button>
      </aside>

      <nav className="fixed bottom-2 left-2 right-2 z-40 md:hidden">
        <div className="relative flex h-[66px] items-center justify-around rounded-2xl border border-[#e0e2e9] bg-white px-1 shadow-[0_10px_30px_rgba(18,24,40,0.12)]">
          <MobileNavItem to="/Professor/dashboard" icon="bxs-dashboard" label="Home" />
          <MobileNavItem to="/Professor/exams" icon="bx-file" label="Exams" />

          <NavLink
            to="/Professor/upload"
            className="relative -mt-8 flex h-16 w-16 shrink-0 items-center justify-center rounded-full border-4 border-[#f7f8fb] bg-[#291C57] text-white shadow-[0_8px_20px_rgba(41,28,87,0.3)] transition-transform active:scale-95"
            aria-label="Upload answer sheets"
          >
            <i className="bx bx-scan text-[28px]" />
          </NavLink>

          <MobileNavItem to="/Professor/ranking" icon="bx-trophy" label="Ranking" />
          <MobileNavItem to="/Professor/settings" icon="bxs-cog" label="Settings" />
        </div>
      </nav>
    </>
  );
}

function MobileNavItem({ to, icon, label }) {
  return (
    <NavLink to={to} className="flex h-full min-w-[52px] items-center justify-center">
      {({ isActive }) => (
        <div className="flex flex-col items-center justify-center gap-0.5">
          <i
            className={`bx ${icon} text-[21px] ${
              isActive ? "text-[#291C57]" : "text-[#7b8496]"
            }`}
          />
          <span
            className={`text-[9px] font-semibold ${
              isActive ? "text-[#291C57]" : "text-[#7b8496]"
            }`}
          >
            {label}
          </span>
        </div>
      )}
    </NavLink>
  );
}

export default ProfessorSidebar;
