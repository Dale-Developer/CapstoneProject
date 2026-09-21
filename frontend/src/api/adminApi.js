import { apiRequest } from "./client";

export const getAdminOverview = () => apiRequest("/admin/overview");

export const getSystemHealth = () => apiRequest("/admin/system");

export function listUsers({ search = "", role = "" } = {}) {
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  if (role) params.set("role", role);
  const query = params.toString();
  return apiRequest(`/admin/users${query ? `?${query}` : ""}`);
}

export const createUser = (payload) =>
  apiRequest("/admin/users", { method: "POST", body: JSON.stringify(payload) });

export const changeUserRole = (userId, role) =>
  apiRequest(`/admin/users/${userId}/role`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  });

export const resetUserPassword = (userId, password) =>
  apiRequest(`/admin/users/${userId}/password`, {
    method: "PUT",
    body: JSON.stringify({ password }),
  });

export const deleteUser = (userId) =>
  apiRequest(`/admin/users/${userId}`, { method: "DELETE" });

export function listSecurityLog({ search = "", type = "", limit = 25, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  if (type) params.set("type", type);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return apiRequest(`/admin/security-log?${params.toString()}`);
}