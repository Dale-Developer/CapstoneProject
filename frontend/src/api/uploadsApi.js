import { apiRequest } from "./client";

// Match the student using whichever answer-sheet page contains the
// identification fields. MCQ exams use Page 1; essay-only exams use the
// first essay page. The essay portion can span any number of pages (2 essay
// answers per printed page), so essayPages is an ordered array of files.
export const matchAnswerSheetOwner = ({ examId, page1, essayPages = [], signal }) => {
  const formData = new FormData();
  formData.append("exam_id", String(examId));
  if (page1) formData.append("page1", page1);
  essayPages.forEach((file) => {
    if (file) formData.append("essay_pages", file);
  });
  return apiRequest("/uploads/match", { method: "POST", body: formData, signal });
};

// Does this student already have a processed sheet for this exam? Called
// once a student is confirmed so the professor is warned about replacing
// existing scores before uploading rather than after processing.
export const getSubmissionStatus = (examId, studentId) =>
  apiRequest(`/uploads/submissions/status?exam_id=${examId}&student_id=${studentId}`);

// Save only the pages required by the selected examination type.
// allowReplace must be true to overwrite a submission that has already been
// processed; the backend rejects the upload with 409 otherwise.
export const uploadAnswerSheetForStudent = ({ examId, studentId, page1, essayPages = [], allowReplace = false }) => {
  const formData = new FormData();
  formData.append("exam_id", String(examId));
  formData.append("student_id", String(studentId));
  formData.append("allow_replace", allowReplace ? "true" : "false");
  if (page1) formData.append("page1", page1);
  essayPages.forEach((file) => {
    if (file) formData.append("essay_pages", file);
  });
  return apiRequest("/uploads/submissions", { method: "POST", body: formData });
};
