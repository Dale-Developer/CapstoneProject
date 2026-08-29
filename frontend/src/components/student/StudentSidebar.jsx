import { NavLink, useNavigate } from "react-router-dom";
import { clearSession } from "../../api/session";

const NAV_ITEMS = [
  { label: "Dashboard", to: "/student", icon: "bxs-dashboard", end: true },
  { label: "Upload", to: "/student/upload", icon: "bx-scan" },
  { label: "Settings", to: "/student/settings", icon: "bxs-cog" },
];

function navClass({ isActive }) {
  return [
    "group flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition-all duration-200",
    isActive
      ? "bg-[#291C57] text-white shadow-[0_8px_18px_rgba(41,28,87,0.18)]"
      : "text-[#0B1739] hover:bg-[#f0eff5] hover:text-[#291C57]",
  ].join(" ");
}
function StudentSidebar() {
  const navigate = useNavigate();
  const logout = () => {
    clearSession();
    window.location.href = "/";
  };
  return (
    <>
      <aside className="hidden w-54 shrink-0 border-r border-[#e4e6ed] bg-white md:flex md:min-h-[calc(100dvh-66px)] md:flex-col">
        <nav className="flex flex-1 flex-col gap-1 px-2 py-5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={navClass}
            >
              {({ isActive }) => (
                <>
                  <i
                    className={`bx ${item.icon} text-[20px] ${
                      isActive ? "text-white" : "text-[#0B1739]"
                    }`}
                  />
                  <span>{item.label.toUpperCase()}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <button
          onClick={logout}
          className="mx-2 mb-5 flex items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-semibold text-[#0B1739] transition hover:bg-[#f0eff5] hover:text-[#291C57]"
        >
          <i className="bx bx-log-out text-[20px]" />
          LOGOUT
        </button>
      </aside>
      <nav className="fixed bottom-2 left-2 right-2 z-40 md:hidden">
        <div className="relative flex h-16.5 items-center justify-around rounded-2xl border border-[#e0e2e9] bg-white px-1 shadow-[0_10px_30px_rgba(18,24,40,0.12)]">
          <MobileItem to="/student" icon="bxs-dashboard" label="Home" end />
          <MobileItem to="/student/upload" icon="bx-scan" label="Upload" />
          <MobileItem to="/student/settings" icon="bxs-cog" label="Settings" />
        </div>
      </nav>
    </>
  );
}
function MobileItem({ to, icon, label, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className="flex h-full min-w-[72px] items-center justify-center"
    >
      {({ isActive }) => (
        <div className="flex flex-col items-center justify-center gap-0.5">
          <i
            className={`bx ${icon} text-[21px] ${isActive ? "text-[#291C57]" : "text-[#7b8496]"}`}
          />
          <span
            className={`text-[9px] font-semibold ${isActive ? "text-[#291C57]" : "text-[#7b8496]"}`}
          >
            {label}
          </span>
        </div>
      )}
    </NavLink>
  );
}
export default StudentSidebar;
