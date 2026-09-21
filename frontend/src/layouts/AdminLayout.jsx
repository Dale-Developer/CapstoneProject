import { Outlet } from "react-router-dom";
import AdminSidebar from "../components/admin/AdminSidebar";
import ProfessorTopbar from "../components/prof/ProfessorTopbar";

/** Shell for the administration section.
 *
 * Reuses the professor topbar so the brand header stays consistent, but
 * deliberately passes no onAdd handler: "create a class" is not an
 * administrator action, and an admin owns no classes.
 */
function AdminLayout({ user, onLogout }) {
  return (
    <div className="flex h-dvh min-h-screen flex-col overflow-hidden bg-[#F7F8FB]">
      <ProfessorTopbar user={user} />
      <div className="flex min-h-0 flex-1">
        <AdminSidebar onLogout={onLogout} />
        <main className="min-w-0 flex-1 overflow-y-auto bg-[#F7F8FB]">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default AdminLayout;
