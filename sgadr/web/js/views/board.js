// Situación: qué está pasando ahora y qué requiere la atención de este rol.
import { clockEl } from "../clocks.js";
import { h, plural } from "../dom.js";
import { DEMAND_STATES, PIPELINE, levelBadge, tag } from "../labels.js";
import { byUrgency, dataSignature, isLate, isOpenAlert, isOpenDemand } from "../rules.js";
import { canSeeAlerts, select as selectItem, setView, state } from "../store.js";
import { empty } from "./../ui.js";
import { markSelected } from "./common.js";

const NEEDS = {
  nodo_07: { alerts: (a) => isLate(a) && "Reporte de estado vencido: pídalo al municipio", demands: () => "" },
  nodo_00: {
    alerts: (a) => (a.state === "pendiente_verificacion" && "Falta verificar con APA y Policía")
      || (a.state === "activa" && !a.center_informed_at && "Falta informar al Centro de Operaciones") || "",
    demands: (d) => ({ recibida: "Falta verificar los datos", verificada: "Falta pedir autorización al Comité", autorizada: "Falta asignar un área",
      recursos_agotados: "El área no tiene recursos: reasignar", respondida: "Respondida: falta cerrarla" })[d.state] ?? "",
  },
  comite: { alerts: () => "", demands: (d) => (d.state === "pendiente_autorizacion" ? "Espera su autorización" : "") },
  monitoreo: { alerts: (a) => (isLate(a) && "Reporte de estado vencido") || "", demands: (d) => (d.state === "recursos_agotados" ? "Recursos agotados" : "") },
  area: { alerts: () => "", demands: (d) => ({ asignada: "Asignada: inicie la respuesta", en_ejecucion: "En ejecución: informe la respuesta" })[d.state] ?? "" },
};

function attentionRow(kind, item, reason) {
  const title = kind === "alert" ? item.municipality : `${item.quantity} × ${item.resource_type}`;
  const sub = kind === "alert" ? item.code : `${item.municipality}, ${item.code}`;
  return h("button", { type: "button", class: "row attn-row", dataset: { kind, id: item.id }, "aria-selected": "false", onclick: () => selectItem(kind, item.id) },
    levelBadge(kind === "alert" ? item.level : item.alert_level),
    h("span", { class: "row-main" }, h("strong", {}, title), h("span", { class: "muted" }, sub)),
    h("span", { class: "row-state" }, tag(reason, "warn")));
}

function summary(alerts, open, late) {
  if (!canSeeAlerts()) return open.length ? `Su área tiene ${plural(open.length, "demanda abierta", "demandas abiertas")}.` : "Su área no tiene demandas abiertas.";
  const live = alerts.filter((a) => a.state === "activa").length;
  const parts = [live ? plural(live, "alerta activa", "alertas activas") : "Sin alertas activas", plural(open.length, "demanda abierta", "demandas abiertas")];
  if (late) parts.push(plural(late, "reporte vencido", "reportes vencidos"));
  return `${parts.join(", ")}.`;
}

export function renderBoard(container) {
  const sig = `${dataSignature()}|${state.me.role}`;
  if (container.dataset.sig === sig) { markSelected(container); return; }
  container.dataset.sig = sig;
  const needs = NEEDS[state.me.role];
  const alerts = state.alerts.filter(isOpenAlert).sort(byUrgency);
  const openDemands = state.demands.filter(isOpenDemand);
  const late = alerts.filter(isLate).length;
  const queue = [
    ...alerts.map((a) => [a, "alert", needs.alerts(a)]),
    ...openDemands.map((d) => [d, "demand", needs.demands(d)]),
  ].filter(([, , reason]) => reason);

  const stages = PIPELINE.map((s) => ({ s, n: openDemands.filter((d) => d.state === s).length }));
  const side = openDemands.filter((d) => d.state === "recursos_agotados").length;

  container.replaceChildren(
    h("header", { class: "view-head" }, h("h1", {}, "Situación")),
    h("p", { class: "lede" }, summary(alerts, openDemands, late)),
    h("section", { class: "block" }, h("h2", {}, "Requiere su atención"),
      queue.length ? h("div", { class: "rows" }, queue.map(([item, kind, reason]) => attentionRow(kind, item, reason)))
        : empty("Nada pendiente", "Cuando algo necesite su acción, aparece aquí.")),
    canSeeAlerts() ? h("section", { class: "block" }, h("h2", {}, "Alertas vigentes"),
      alerts.length ? h("div", { class: "rows" }, alerts.map((a) => h("button", { type: "button", class: "row alert-row", dataset: { kind: "alert", id: a.id },
        "aria-selected": "false", onclick: () => selectItem("alert", a.id) },
      levelBadge(a.level), h("span", { class: "row-main" }, h("strong", {}, a.municipality), h("span", { class: "muted" }, a.code)),
      h("span", { class: "row-state" }, tag(a.state === "activa" ? "Activa" : "Pendiente de verificación", a.state === "activa" ? "ok" : "neutral")),
      a.state === "activa" ? clockEl(a) : h("span")))) : empty("No hay alertas vigentes")) : null,
    h("section", { class: "block" }, h("h2", {}, "Circuito de demandas"),
      h("ol", { class: "flow" }, stages.map(({ s, n }) => h("li", { class: n ? "has" : "" },
        h("button", { type: "button", class: "flow-btn", onclick: () => { state.filters.demandState = s; setView("demandas"); } },
          h("span", { class: "flow-n" }, n), h("span", { class: "flow-l" }, DEMAND_STATES[s]))))),
      side ? h("p", { class: "muted" }, `${plural(side, "demanda", "demandas")} en recursos agotados, fuera del circuito principal.`) : null),
  );
  markSelected(container);
}
