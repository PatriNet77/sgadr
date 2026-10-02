// Estado compartido de la aplicación y sincronización con el servidor.
import { api, ApiError } from "./api.js";
import { ROLES } from "./labels.js";

export const state = {
  me: null,
  meta: null,
  alerts: [],
  demands: [],
  audit: [],
  users: [],
  auditCheck: null, // { valid: boolean, at: Date } | null
  offsetMs: 0, // diferencia entre la hora del servidor y la de este equipo
  lastSync: null,
  online: true,
  view: "tablero",
  selected: null, // { kind: "alert" | "demand", id }
  filters: { alerts: "vigentes", alertQuery: "", demands: "abiertas", demandQuery: "", demandState: "" },
};

const listeners = new Set();
export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
export const notify = () => { for (const fn of listeners) fn(); };

export const serverNow = () => new Date(Date.now() + state.offsetMs);
export const canSeeAlerts = () => !["area", "admin"].includes(state.me?.role);
export const canSeeDemands = () => state.me?.role !== "admin";
export const isAdmin = () => state.me?.role === "admin";
export const canSeeAudit = () => ["comite", "monitoreo"].includes(state.me?.role);

function syncClock(serverTime) {
  state.offsetMs = Date.parse(serverTime) - Date.now();
}

/** Carga la sesión. Con clave temporal el servidor solo permite /me: devuelve false y no hay catálogos. */
export async function bootstrap() {
  const me = await api.me();
  state.me = me;
  syncClock(me.server_time);
  if (me.must_change_password) return false;
  state.meta = await api.meta();
  state.view = ROLES[me.role].tabs[0];
  return true;
}

export function resetState() {
  Object.assign(state, {
    me: null, meta: null, alerts: [], demands: [], audit: [], users: [], auditCheck: null, lastSync: null,
    online: true, view: "tablero", selected: null,
    filters: { alerts: "vigentes", alertQuery: "", demands: "abiertas", demandQuery: "", demandState: "" },
  });
}

export function setView(view) {
  state.view = view;
  state.selected = null;
  notify();
  if (view === "bitacora") refresh().catch(() => {});
}

export function select(kind, id) {
  state.selected = { kind, id };
  notify();
}

export function closeDetail() {
  if (!state.selected) return;
  state.selected = null;
  notify();
}

export async function loadAudit() {
  state.audit = (await api.audit(100)).items;
}

export async function checkAudit() {
  const { valid } = await api.verifyAudit();
  state.auditCheck = { valid, at: serverNow() };
  notify();
}

let inFlight = null;

/** Trae el estado actual del servidor. Reúne llamadas simultáneas en una sola. */
export function refresh() {
  if (!inFlight) inFlight = doRefresh().finally(() => { inFlight = null; });
  return inFlight;
}

async function doRefresh() {
  try {
    const jobs = [
      api.me().then((me) => syncClock(me.server_time)),
    ];
    if (canSeeDemands()) jobs.push(api.demands(true).then((r) => { state.demands = r.items; }));
    if (isAdmin()) jobs.push(api.users().then((r) => { state.users = r.items; }));
    if (canSeeAlerts()) jobs.push(api.alerts(true).then((r) => { state.alerts = r.items; }));
    if (canSeeAudit() && state.view === "bitacora") jobs.push(loadAudit());
    await Promise.all(jobs);
    state.online = true;
    state.lastSync = new Date();
  } catch (error) {
    if (error instanceof ApiError && error.status === 0) state.online = false;
    else throw error;
  } finally {
    notify();
  }
}
