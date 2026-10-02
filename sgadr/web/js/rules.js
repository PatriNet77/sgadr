// Reglas derivadas de los datos del servidor (el servidor sigue siendo la fuente de verdad:
// las transiciones permitidas llegan en /meta y se filtran por el rol de la persona).
import { normalizeKey } from "./dom.js";
import { ACTION_LABELS } from "./labels.js";
import { serverNow, state } from "./store.js";

export const OPEN_ALERT = new Set(["pendiente_verificacion", "activa"]);
export const CLOSED_DEMAND = new Set(["cerrada", "rechazada"]);
export const LEVEL_RANK = { rojo: 3, naranja: 2, amarillo: 1 };

export const isOpenAlert = (a) => OPEN_ALERT.has(a.state);
export const isOpenDemand = (d) => !CLOSED_DEMAND.has(d.state);

export const isLate = (a) =>
  a.state === "activa" && Boolean(a.next_report_due_at) && Date.parse(a.next_report_due_at) <= serverNow().getTime();

/** Acciones que el rol actual puede ejecutar sobre una demanda en su estado actual. */
export const transitionsFor = (d) =>
  state.meta.demand_transitions.filter((t) => t.from === d.state && t.roles.includes(state.me.role));

export const actionLabel = (t) =>
  t.from === "recursos_agotados" && t.to === "asignada" ? "Reasignar área" : ACTION_LABELS[t.to];

export const suggestedArea = (resourceName) =>
  state.meta.resources.find((r) => r.name === resourceName)?.suggested_area ?? "";

export const activeAlertFor = (municipality) => {
  const key = normalizeKey(municipality);
  return key ? state.alerts.find((a) => a.state === "activa" && normalizeKey(a.municipality) === key) : undefined;
};

/** Firma de los datos: permite no reconstruir una lista que no cambió (conserva foco y desplazamiento). */
export const dataSignature = () =>
  [
    state.alerts.map((a) => `${a.id}:${a.version}`).join(","),
    state.demands.map((d) => `${d.id}:${d.version}`).join(","),
    state.alerts.filter(isLate).length,
    JSON.stringify(state.filters),
    state.audit.length ? state.audit[0].seq : 0,
    state.users.map((u) => `${u.username}:${u.active}:${u.locked}:${u.must_change_password}`).join(","),
    state.auditCheck ? `${state.auditCheck.valid}${state.auditCheck.at.getTime()}` : "",
  ].join("|");

export const byUrgency = (a, b) =>
  (Number(isOpenAlert(b)) - Number(isOpenAlert(a))) ||
  (LEVEL_RANK[b.level] - LEVEL_RANK[a.level]) ||
  String(a.next_report_due_at ?? "9").localeCompare(String(b.next_report_due_at ?? "9")) ||
  b.id - a.id;
