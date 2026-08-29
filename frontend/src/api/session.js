export const getStoredUser = () => {
  try {
    const raw = localStorage.getItem("esscan_user");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

export const saveSession = (token, user) => {
  localStorage.setItem("esscan_access_token", token);
  localStorage.setItem("esscan_user", JSON.stringify(user));
};

export const clearSession = () => {
  localStorage.removeItem("esscan_access_token");
  localStorage.removeItem("esscan_user");
};

export const isAuthenticated = () => Boolean(localStorage.getItem("esscan_access_token"));
