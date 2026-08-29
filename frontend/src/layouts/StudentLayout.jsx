import { Outlet } from "react-router-dom";
import StudentSidebar from "../components/student/StudentSidebar";
import StudentTopbar from "../components/student/StudentTopbar";

export default function StudentLayout({ user }) {
  return (
    <div className="flex h-dvh min-h-screen flex-col overflow-hidden bg-[#F7F8FB]">
      <StudentTopbar user={user} />
      <div className="flex min-h-0 flex-1">
        <StudentSidebar />
        <main className="min-w-0 flex-1 overflow-y-auto bg-[#F7F8FB]">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
