// API client. The access token lives only in this module's memory; the refresh token is an HttpOnly cookie.
let token = null;
let refreshing = null;
let onExpired = () => {};

export class ApiError extends Error {
  constructor(status, body, retryAfter) {
    super(body.error || "Something went wrong");
    this.status = status;
    this.errors = body.errors || {};
    this.current = body.current;
    this.retryAfter = retryAfter;
  }
}

export const setExpiredHandler = (fn) => { onExpired = fn; };
export const hasToken = () => token !== null;

function send(method, path, body, binary) {
  const headers = { "X-Requested-With": "ats-web" };
  if (token) headers.Authorization = "Bearer " + token;
  let payload;
  if (binary) { headers["Content-Type"] = "application/octet-stream"; payload = body; }
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  return fetch("/api/v1" + path, { method, headers, body: payload, credentials: "same-origin" });
}

function adopt(data) {
  token = data.access_token;
  return data.user;
}

// One refresh at a time: parallel callers share the same request so the rotating cookie is never reused.
export function refreshSession() {
  if (!refreshing) {
    refreshing = send("POST", "/auth/refresh")
      .then(async (res) => (res.ok ? adopt(await res.json()) : null))
      .catch(() => null)
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function parse(res) {
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data, res.headers.get("Retry-After"));
  return data;
}

export async function request(method, path, body, binary = false) {
  let res = await send(method, path, body, binary);
  if (res.status === 401 && !path.startsWith("/auth")) {
    if (await refreshSession()) res = await send(method, path, body, binary);
    else { token = null; onExpired(); }
  }
  return parse(res);
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  put: (p, b) => request("PUT", p, b),
  patch: (p, b) => request("PATCH", p, b),
  del: (p) => request("DELETE", p),
  upload: (p, buf) => request("POST", p, buf, true),
  putFile: (p, buf) => request("PUT", p, buf, true),
  async download(path, filename) {
    let res = await send("GET", path);
    if (res.status === 401 && (await refreshSession())) res = await send("GET", path);
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => ({})), res.headers.get("Retry-After"));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  async login(email, password) {
    return adopt(await request("POST", "/auth/login", { email, password }));
  },
  async signup(body) {
    return adopt(await request("POST", "/auth/signup", body));
  },
  async logout() {
    try { await request("POST", "/auth/logout", {}); } finally { token = null; }
  },
};

export const qs = (params) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => x !== "" && u.append(k, x));
    else if (v !== "" && v != null) u.set(k, v);
  }
  const s = u.toString();
  return s ? "?" + s : "";
};