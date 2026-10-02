// Bitácora inmutable con verificación de la cadena de hashes (solo Comité y Monitoreo).
import { h, fmtDateTime } from "../dom.js";
import { ACTION_LOG, ALERT_STATES, DEMAND_STATES } from "../labels.js";
import { checkAudit, state } from "../store.js";
import { empty, press } from "../ui.js";
import { mountView } from "./common.js";

const st = (v) => DEMAND_STATES[v] ?? ALERT_STATES[v] ?? v;
// Quién actuó: `actor` (circuito), `by` (administración de cuentas, donde `user` es la cuenta afectada) o `user` (ingreso/salida).
const who = (e) => (e.actor ? `${e.actor}${e.role && e.role !== "system" ? ` (${e.role})` : ""}` : e.by ?? e.user ?? "Sistema");
const detail = (e) => [e.by && e.user && `Cuenta ${e.user}`, e.demand && `Demanda ${e.demand}`, e.alert && `Alerta ${e.alert}`, e.from && e.to ? `${st(e.from)} a ${st(e.to)}` : e.to && st(e.to), e.level && `nivel ${e.level}`, e.note]
  .filter(Boolean).join(", ");

export function renderAudit(container) {
  const entry = mountView(container, "bitacora", (root) => {
    const verdict = h("p", { class: "verdict", role: "status" });
    const btn = h("button", { type: "button", class: "btn", onclick: (e) => press(e.currentTarget, checkAudit, () => "Verificación terminada.") }, "Verificar integridad");
    const body = h("tbody");
    root.append(h("header", { class: "view-head" }, h("h1", {}, "Bitácora"), btn),
      verdict, h("div", { class: "table-wrap" }, h("table", { class: "log" },
        h("thead", {}, h("tr", {}, ["Fecha", "Persona", "Acción", "Detalle", "Sello"].map((t) => h("th", { scope: "col" }, t)))), body)));
    return { verdict, body };
  });
  const { verdict, body } = entry.refs;
  const c = state.auditCheck;
  verdict.className = `verdict ${c ? (c.valid ? "ok" : "bad") : ""}`;
  verdict.textContent = c ? (c.valid ? "La cadena de registros está íntegra: ningún registro fue alterado." : "Atención: la cadena de registros fue alterada. Escale a Seguridad de la Información.")
    : "Todavía no se verificó la integridad en esta sesión.";
  const sig = state.audit.map((r) => r.seq).join(",");
  if (sig !== entry.sig) {
    entry.sig = sig;
    body.replaceChildren(...state.audit.map((r) => h("tr", {}, h("td", {}, fmtDateTime(r.entry.ts)), h("td", {}, who(r.entry)),
      h("td", {}, ACTION_LOG[r.entry.action] ?? r.entry.action), h("td", {}, detail(r.entry)), h("td", { class: "mono" }, r.hash))));
    if (!state.audit.length) body.append(h("tr", {}, h("td", { colspan: 5 }, empty("Sin registros", "Todavía no hay actividad registrada."))));
  }
}
