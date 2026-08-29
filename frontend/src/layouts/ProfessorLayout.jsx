import { useState } from "react";
import { Outlet } from "react-router-dom";
import ProfessorSidebar from "../components/prof/ProfessorSidebar";
import ProfessorTopbar from "../components/prof/ProfessorTopbar";
import CreateClassModal from "../components/prof/CreateClassModal";
import { createClass } from "../api/classesApi";

function ProfessorLayout({ user, onLogout }) {
  const [isCreateClassOpen, setIsCreateClassOpen] = useState(false);

  const handleCreate = async (classData) => {
    await createClass(classData);
    window.dispatchEvent(new CustomEvent("esscan:classes-changed"));
  };

  return (
    <div className="flex h-dvh min-h-screen flex-col overflow-hidden bg-[#F7F8FB]">
      <ProfessorTopbar user={user} onAdd={() => setIsCreateClassOpen(true)} />
      <div className="flex min-h-0 flex-1">
        <ProfessorSidebar onLogout={onLogout} />
        <main className="min-w-0 flex-1 overflow-y-auto bg-[#F7F8FB]">
          <Outlet />
        </main>
      </div>
      <CreateClassModal
        isOpen={isCreateClassOpen}
        onClose={() => setIsCreateClassOpen(false)}
        onCreate={handleCreate}
      />
    </div>
  );
}

export default ProfessorLayout;
