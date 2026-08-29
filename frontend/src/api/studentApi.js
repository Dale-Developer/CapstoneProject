import { apiRequest } from "./client";

export const getStudentExams = () => apiRequest("/student/exams");
export const getStudentExam = (examId) => apiRequest(`/student/exams/${examId}`);

// The student's own scored result. The backend returns `released: false` and
// no numbers until the professor releases the score, so this is safe to call
// at any time.
export const getStudentResult = (examId) => apiRequest(`/student/exams/${examId}/result`);

// essayPages is an ordered array of files - 2 essay answers per printed
// page, so the number of pages required scales with the exam's essay count.
export async function uploadStudentAnswerSheet({ examId, page1, essayPages = [] }) {
  const form = new FormData();
  if (page1) form.append("page1", page1);
  essayPages.forEach((file) => {
    if (file) form.append("essay_pages", file);
  });
  return apiRequest(`/student/exams/${examId}/upload`, { method: "POST", body: form });
}
