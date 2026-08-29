import { apiRequest } from "./client";

export const getProfile = () => apiRequest("/profile");
export const updateProfile = (payload) =>
  apiRequest("/profile", { method: "PUT", body: JSON.stringify(payload) });
export const updatePassword = (payload) =>
  apiRequest("/profile/password", { method: "PUT", body: JSON.stringify(payload) });
