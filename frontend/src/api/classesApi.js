import { apiRequest } from "./client";

export const getClasses = () => apiRequest("/classes");
export const getClass = (classId) => apiRequest(`/classes/${classId}`);
export const getClassStudents = (classId) => apiRequest(`/classes/${classId}/students`);
export const createClass = (payload) =>
  apiRequest("/classes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateClass = (classId, payload) =>
  apiRequest(`/classes/${classId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export const joinClass = (classCode) =>
  apiRequest("/classes/join", {
    method: "POST",
    body: JSON.stringify({ classCode }),
  });
