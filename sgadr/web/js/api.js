// Cliente de la API REST. El token vive en sessionStorage: se descarta al cerrar la pestaña.
const KEY = "sgadr.token";

const read = () => {
  try { return sessionStorage.getItem(KEY); } catch { return null; }
};
let token = read();

export const session = {
  get token() { return token; },
  set(value) {
    token = value;
    try { sessionStorage.setItem(KEY, value); } catch { /* navegación privada: queda solo en memoria */ }
  },
  clear() {
    token = null;
    try { sessionStorage.removeItem(KEY); } catch { /* sin acción */ }
  },
};

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status; // 0 = sin conexión
    this.code = code;
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(method, path, body) {
  const headers = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network", "No hay conexión con el servidor.");
  }

  let data = null;
  try { data = await response.json(); } catch { /* cuerpo vacío o no JSON */ }

  if (!response.ok) {
    const error = data?.error ?? {};
    if (response.status === 401 && path !== "/login") onUnauthorized();
    throw new ApiError(response.status, error.code ?? "error", error.message ?? `Error ${response.status}`);
  }
  return data;
}

export const api = {
  login: (username, password) => request("POST", "/login", { username, password }),
  logout: () => request("POST", "/logout"),
  me: () => request("GET", "/me"),
  meta: () => request("GET", "/meta"),

  alerts: (all) => request("GET", `/alerts?all=${all ? 1 : 0}`),
  alert: (id) => request("GET", `/alerts/${id}`),
  registerAlert: (body) => request("POST", "/alerts", body),
  verifyAlert: (id, body) => request("POST", `/alerts/${id}/verify`, body),
  informCenter: (id, expected_version) => request("POST", `/alerts/${id}/center-informed`, { expected_version }),
  reportAlert: (id, body) => request("POST", `/alerts/${id}/reports`, body),
  changeLevel: (id, body) => request("POST", `/alerts/${id}/level`, body),

  demands: (all) => request("GET", `/demands?all=${all ? 1 : 0}`),
  registerDemand: (body) => request("POST", "/demands", body),
  transition: (id, body) => request("POST", `/demands/${id}/transition`, body),

  users: () => request("GET", "/users"),
  createUser: (body) => request("POST", "/users", body),
  setUserActive: (username, active) => request("POST", `/users/${username}/active`, { active }),
  resetPassword: (username, temporary_password) => request("POST", `/users/${username}/password`, { temporary_password }),
  changePassword: (current_password, new_password) => request("POST", "/password", { current_password, new_password }),

  audit: (limit = 100) => request("GET", `/audit?limit=${limit}`),
  verifyAudit: () => request("GET", "/audit/verify"),
};
