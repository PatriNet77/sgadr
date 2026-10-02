// Demandas: lista, detalle con el circuito de estados y acciones según rol.
import { api } from "../api.js";
import { fmtDateTime, h, normalizeKey, phoneHref } from "../dom.js";
import { DEMAND_STATES, LEVELS, PIPELINE, levelBadge, tag } from "../labels.js";
import { actionLabel, activeAlertFor, isOpenDemand, suggestedArea, transitionsFor } from "../rules.js";
import { select as selectItem, state } from "../store.js";
import { PHONE_PATTERN, PHONE_TITLE, act, datalist, empty, field, input, modal, select as selectField, textarea } from "../ui.js";
import { facts, markSelected, mountView, section, segmented } from "./common.js";

const FILTERS = [["abiertas", "Abiertas"], ["todas", "Todas"]];
const STATE_TONE = { recursos_agotados: "bad", rechazada: "neutral", cerrada: "neutral", pendiente_autorizacion: "warn" };

export function openNewDemand() {
  const muni = input("municipality", { required: true, maxlength: 80, list: "dl-muni" });
  const hint = h("p", { class: "hint", "aria-live": "polite" });
  const levelSel = selectField("alert_level", [["", "Según la alerta vigente"], ...Object.entries(LEVELS)]);
  muni.addEventListener("input", () => {
    const a = activeAlertFor(muni.value);
    hint.textContent = a ? `Alerta ${LEVELS[a.level]} vigente en ${a.municipality}: la demanda hereda ese nivel.` : "";
  });
  const body = h("div", { class: "form-grid" },
    field("Municipio", muni), hint, datalist("dl-muni", state.meta.municipalities),
    field("Localidad o paraje", input("locality", { required: true, maxlength: 80 })),
    field("Recurso solicitado", selectField("resource_type", state.meta.resources.map((r) => [r.name, r.name]))),
    field("Cantidad", input("quantity", { type: "number", min: 1, max: 100000, step: 1, required: true, inputmode: "numeric" })),
    field("Motivo", textarea("reason", { required: true, maxlength: 500 })),
    field("Nivel de alerta", levelSel, "Déjelo así salvo que no haya alerta vigente en el municipio."),
    field("Contacto en el municipio", input("contact_name", { required: true, maxlength: 80 })),
    field("Teléfono de contacto", input("contact_phone", { type: "tel", required: true, pattern: PHONE_PATTERN, title: PHONE_TITLE })));
  modal({
    title: "Registrar demanda", intro: "El Nodo 00 la verifica antes de pedir autorización al Comité.", body, submitLabel: "Registrar demanda",
    onSubmit: (f) => {
      const payload = {
        municipality: f.get("municipality"), locality: f.get("locality"), resource_type: f.get("resource_type"),
        quantity: Number(f.get("quantity")), reason: f.get("reason"), contact_name: f.get("contact_name"), contact_phone: f.get("contact_phone"),
      };
      if (f.get("alert_level")) payload.alert_level = f.get("alert_level");
      return act(() => api.registerDemand(payload), (d) => `Demanda ${d.code} registrada.`);
    },
  });
}

function matches(d) {
  const q = normalizeKey(state.filters.demandQuery);
  if (q && !normalizeKey(`${d.municipality} ${d.locality} ${d.code} ${d.resource_type}`).includes(q)) return false;
  if (state.filters.demandState) return d.state === state.filters.demandState;
  return state.filters.demands === "todas" || isOpenDemand(d);
}

const byDemand = (a, b) => (Number(isOpenDemand(b)) - Number(isOpenDemand(a))) || b.id - a.id;

export function demandRow(d) {
  return h("button", { type: "button", class: "row demand-row", dataset: { kind: "demand", id: d.id }, "aria-selected": "false",
    onclick: () => selectItem("demand", d.id) },
  levelBadge(d.alert_level),
  h("span", { class: "row-main" }, h("strong", {}, `${d.quantity} × ${d.resource_type}`), h("span", { class: "muted" }, `${d.municipality}, ${d.locality}`)),
  h("span", { class: "row-state" }, tag(DEMAND_STATES[d.state], STATE_TONE[d.state] ?? "neutral"),
    d.assigned_area ? h("span", { class: "muted small" }, d.assigned_area) : null),
  h("span", { class: "muted small row-code" }, d.code));
}

export function renderDemands(container) {
  const entry = mountView(container, "demandas", (root) => {
    const search = h("input", { type: "search", class: "search", placeholder: "Buscar municipio, recurso o código", "aria-label": "Buscar demanda",
      oninput: (e) => { state.filters.demandQuery = e.target.value; render(); } });
    const seg = segmented("Filtro de demandas", FILTERS, () => state.filters.demands, (v) => { state.filters.demands = v; render(); });
    const create = state.me.role === "nodo_07"
      ? h("button", { type: "button", class: "btn primary", onclick: openNewDemand }, "Registrar demanda") : null;
    const list = h("div", { class: "rows", role: "list" });
    const chip = h("button", { type: "button", class: "btn", hidden: true, onclick: () => { state.filters.demandState = ""; render(); } });
    root.append(h("header", { class: "view-head" }, h("h1", {}, "Demandas"), create), h("div", { class: "toolbar" }, search, seg.el, chip), list);
    const render = () => { entry.sig = ""; renderDemands(container); };
    return { seg, list, chip };
  });
  const { seg, list, chip } = entry.refs;
  seg.sync();
  chip.hidden = !state.filters.demandState;
  chip.textContent = `Estado: ${DEMAND_STATES[state.filters.demandState] ?? ""}. Quitar filtro`;
  const items = state.demands.filter(matches).sort(byDemand);
  const sig = items.map((d) => `${d.id}:${d.version}`).join(",") + state.filters.demands + state.filters.demandState;
  if (sig !== entry.sig) {
    entry.sig = sig;
    list.replaceChildren(...(items.length ? items.map(demandRow)
      : [empty("No hay demandas para mostrar", state.me.role === "area" ? "Aquí aparecen las demandas asignadas a su área." : "Cambie el filtro o registre una demanda.")]));
  }
  markSelected(list);
}

function transitionDialog(d, t) {
  const fields = [];
  if (t.to === "asignada") {
    const sel = selectField("assigned_area", state.meta.areas.map((a) => [a, a]));
    sel.value = d.assigned_area || suggestedArea(d.resource_type) || state.meta.areas[0];
    fields.push(field("Área responsable", sel, "Se sugiere según el tipo de recurso."));
  }
  if (t.to === "respondida")
    fields.push(field("Detalle de la respuesta", textarea("response_detail", { required: true, minlength: 10, maxlength: 4000 }), "Qué se entregó, cuánto y cuándo."));
  const noteRequired = ["rechazada", "recursos_agotados"].includes(t.to);
  fields.push(field(noteRequired ? "Motivo" : "Observación (opcional)", textarea("note", { required: noteRequired, minlength: noteRequired ? 5 : null, maxlength: 1000 })));
  modal({
    title: actionLabel(t), intro: `${d.code}: pasa de ${DEMAND_STATES[d.state]} a ${DEMAND_STATES[t.to]}.`,
    body: h("div", { class: "form-grid" }, fields), submitLabel: actionLabel(t), tone: t.to === "rechazada" ? "danger" : "primary",
    onSubmit: (f) => {
      const body = { target: t.to, expected_version: d.version };
      for (const k of ["assigned_area", "response_detail", "note"]) if (f.get(k) && String(f.get(k)).trim()) body[k] = f.get(k);
      return act(() => api.transition(d.id, body), `${actionLabel(t)}: ${d.code}.`);
    },
  });
}

function pipeline(d) {
  const idx = PIPELINE.indexOf(d.state);
  const closed = d.state === "cerrada";
  return h("ol", { class: "pipe", "aria-label": "Avance de la demanda" }, PIPELINE.map((s, i) =>
    h("li", { class: closed || i < idx ? "done" : i === idx ? "now" : "", "aria-current": i === idx ? "step" : null }, DEMAND_STATES[s])));
}

export function demandDetail(d) {
  const ts = transitionsFor(d);
  const actions = ts.map((t) => h("button", { type: "button", class: t.to === "rechazada" || t.to === "recursos_agotados" ? "btn" : "btn primary",
    onclick: () => transitionDialog(d, t) }, actionLabel(t)));
  return {
    title: `${d.quantity} × ${d.resource_type}`, subtitle: d.code,
    tags: [levelBadge(d.alert_level), tag(DEMAND_STATES[d.state], STATE_TONE[d.state] ?? "neutral")],
    body: [
      actions.length ? h("div", { class: "actions" }, actions) : null,
      ["rechazada", "recursos_agotados"].includes(d.state) ? null : section("Avance", pipeline(d)),
      section("Pedido", h("p", { class: "prose" }, d.reason),
        facts([["Municipio", d.municipality], ["Localidad", d.locality], ["Cantidad", d.quantity], ["Área asignada", d.assigned_area],
          ["Contacto", d.contact_name], ["Teléfono", d.contact_phone ? h("a", { href: phoneHref(d.contact_phone) }, d.contact_phone) : ""],
          ["Registrada", `${fmtDateTime(d.created_at)}, ${d.created_by}`], ["Última novedad", fmtDateTime(d.updated_at)]])),
      d.response_detail ? section("Respuesta", h("p", { class: "prose" }, d.response_detail)) : null,
    ],
  };
}
