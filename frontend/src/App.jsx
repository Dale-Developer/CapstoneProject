import "./App.css";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import AuthForm from "./pages/auth/AuthForm";
import ProfessorLayout from "./layouts/ProfessorLayout";
import Dashboard from "./pages/Professor/Dashboard";
import ClassView from "./pages/Professor/Dashboard/ClassView";
import StudentsList from "./pages/Professor/Dashboard/StudentsList";
import Exams from "./pages/Professor/Exams";
import CreateExam from "./pages/Professor/Exams/CreateExam";
import ExamView from "./pages/Professor/Exams/ExamView";
import ExamStudentSubmission from "./pages/Professor/Exams/ExamStudentSubmission";
import ExamSubmissionDetails from "./pages/Professor/Exams/ExamSubmissionDetails";
import Settings from "./pages/Professor/Settings";
import Ranking from "./pages/Professor/Ranking";
import Upload from "./pages/Professor/Upload";
import StudentDashboard from "./pages/student/StudentDashboard";
import StudentLayout from "./layouts/StudentLayout";
import StudentClassView from "./pages/student/StudentClassView";
import StudentExamView from "./pages/student/StudentExamView";
import StudentUpload from "./pages/student/StudentUpload";
import StudentResult from "./pages/student/StudentResult";
import { clearSession, getStoredUser, isAuthenticated } from "./api/session";

function RequireRole({ role, children }) {
  const location = useLocation();
  const user = getStoredUser();

  if (!isAuthenticated() || !user) {
    return <Navigate to="/" replace state={{ from: location.pathname }} />;
  }

  if (user.role !== role) {
    return <Navigate to={user.role === "teacher" ? "/Professor/dashboard" : "/student"} replace />;
  }

  return children;
}

function App() {
  const user = getStoredUser();

  const handleLogout = () => {
    clearSession();
    window.location.href = "/";
  };

  return (
    <Routes>
      <Route path="/" element={<AuthForm />} />

      <Route
        path="/Professor"
        element={
          <RequireRole role="teacher">
            <ProfessorLayout user={user} onLogout={handleLogout} />
          </RequireRole>
        }
      >
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="dashboard/class/:classId" element={<ClassView />} />
        <Route path="dashboard/class/:classId/students" element={<StudentsList />} />
        <Route path="exams" element={<Exams />} />
        <Route path="exams/createexam" element={<CreateExam />} />
        <Route path="exams/edit/:examId" element={<CreateExam />} />
        <Route path="upload" element={<Upload />} />
        <Route path="classes/:classId/exams/:examId" element={<ExamView />} />
        <Route path="classes/:classId/exams/:examId/students/:studentId" element={<ExamStudentSubmission />} />
        <Route path="classes/:classId/exams/:examId/students/:studentId/details" element={<ExamSubmissionDetails />} />
        <Route path="ranking" element={<Ranking />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      <Route
        path="/student"
        element={
          <RequireRole role="student">
            <StudentLayout user={user} />
          </RequireRole>
        }
      >
        <Route index element={<StudentDashboard />} />
        <Route path="class/:classId" element={<StudentClassView />} />
        <Route path="class/:classId/exam/:examId" element={<StudentExamView />} />
        <Route path="class/:classId/exam/:examId/upload" element={<StudentUpload />} />
        <Route path="class/:classId/exam/:examId/result" element={<StudentResult />} />
        <Route path="upload" element={<StudentUpload />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      <Route path="*" element={<Navigate to={user?.role === "teacher" ? "/Professor/dashboard" : user?.role === "student" ? "/student" : "/"} replace />} />
    </Routes>
  );
}

export default App;
