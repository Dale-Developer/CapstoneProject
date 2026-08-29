import { apiRequest, API_BASE_URL } from "./client";

export const getExams = () => apiRequest("/exams");
export const getExam = (examId) => apiRequest(`/exams/${examId}`);
export const createExam = (payload) =>
  apiRequest("/exams", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateExam = (examId, payload) =>
  apiRequest(`/exams/${examId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export const getExamSubmissions = (examId) => apiRequest(`/exams/${examId}/submissions`);
export const getSubmissionByStudent = (examId, studentId) =>
  apiRequest(`/exams/${examId}/submissions/by-student/${studentId}`);

// Set or clear the professor's manual score for one essay answer. Passing
// score: null clears the override and restores the AI score, so an
// adjustment is always reversible.
export const overrideEssayScore = (examId, studentId, questionId, { score, reason }) =>
  apiRequest(`/exams/${examId}/submissions/by-student/${studentId}/essay/${questionId}/score`, {
    method: "PUT",
    body: JSON.stringify({ score: score === null || score === undefined ? null : Number(score), reason: reason || null }),
  });

// Make one student's score visible to them, or hide it again.
export const releaseStudentScore = (examId, studentId, released = true) =>
  apiRequest(`/exams/${examId}/submissions/by-student/${studentId}/release`, {
    method: "POST",
    body: JSON.stringify({ released }),
  });

// Release or hide scores for a whole exam. An empty studentIds means every
// submission that already has a score.
export const releaseExamScores = (examId, { studentIds = null, released = true } = {}) =>
  apiRequest(`/exams/${examId}/submissions/release`, {
    method: "POST",
    body: JSON.stringify({ studentIds, released }),
  });

// Scanned submission images are served through an authenticated endpoint
// (not a public static path), so fetch them as a blob and hand back an
// object URL the <img> tag can use. Caller is responsible for revoking it
// (e.g. on unmount) once it's no longer displayed.
export async function getSubmissionFileUrl(submissionId, which = "page1", index = 0) {
  const token = localStorage.getItem("esscan_access_token");
  let response;
  try {
    response = await fetch(
      `${API_BASE_URL}/uploads/submissions/${submissionId}/file?which=${which}&index=${index}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
  } catch {
    throw new Error("Unable to connect to the ESSCAN backend.");
  }
  if (!response.ok) throw new Error("That scanned page is not available.");
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}


export async function previewExamPdf(payload) {
  const token = localStorage.getItem("esscan_access_token");
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/exams/preview-pdf`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error("Unable to connect to the ESSCAN backend. Make sure FastAPI is running on http://localhost:8000.");
  }

  if (!response.ok) {
    let detail = "Unable to generate the printable preview.";
    try {
      const body = await response.json();
      const raw = body?.detail;
      if (Array.isArray(raw)) detail = raw.map((item) => item?.msg || String(item)).join("; ");
      else if (raw && typeof raw === "object") detail = raw.message || raw.msg || JSON.stringify(raw);
      else if (raw) detail = String(raw);
    } catch {}
    throw new Error(detail);
  }
  return response.blob();
}

export function openBlobInNewTab(blob) {
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function downloadExamPdf(examId) {
  const token = localStorage.getItem("esscan_access_token");
  const response = await fetch(`${API_BASE_URL}/exams/${examId}/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let detail = "Unable to generate the exam PDF.";
    try {
      const body = await response.json();
      const raw = body?.detail;
      if (Array.isArray(raw)) detail = raw.map((item) => item?.msg || String(item)).join("; ");
      else if (raw && typeof raw === "object") detail = raw.message || raw.msg || JSON.stringify(raw);
      else if (raw) detail = String(raw);
    } catch {
      const text = await response.text().catch(() => "");
      if (text) detail = text;
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] || `ESSCAN_Exam_${examId}.pdf`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
