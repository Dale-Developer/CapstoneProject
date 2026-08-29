import { apiRequest } from "./client";

export const getRanking = (params = {}) => {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/ranking${query ? `?${query}` : ""}`);
};
