const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api"
).replace(/\/*$/, "");

console.log("ESSCAN API BASE URL:", API_BASE_URL);

export async function apiRequest(path, options = {}) {
  const token = localStorage.getItem("esscan_access_token");
  const headers = new Headers(options.headers || {});

  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    });
  } catch (err) {
    // A deliberate cancellation (AbortController.abort()) must stay
    // distinguishable from a real connectivity failure — callers rely on
    // checking err.name === "AbortError" to skip showing an error message
    // for a request they intentionally cancelled (e.g. swapping a photo
    // before identification finished). Only wrap genuine network failures.
    if (err?.name === "AbortError") throw err;
    throw new Error(
      "Unable to connect to the ESSCAN backend. Make sure FastAPI is running on http://localhost:8000."
    );
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem("esscan_access_token");
      localStorage.removeItem("esscan_user");
    }

    const rawDetail = typeof payload === "string" ? payload : payload?.detail;
    let detail = rawDetail || "Request failed";
    if (Array.isArray(detail)) {
      detail = detail.map((item) => typeof item === "string" ? item : item?.msg || JSON.stringify(item)).join("; ");
    } else if (typeof detail === "object") {
      detail = detail?.message || detail?.msg || JSON.stringify(detail);
    }
    throw new Error(String(detail));
  }

  return payload;
}

export { API_BASE_URL };
