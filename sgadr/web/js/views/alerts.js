// Alertas: lista vigente y detalle con las acciones de cada rol (circuitos 1 a 3 del documento).
import { api } from "../api.js";
import { clockEl } from "../clocks.js";
import { fmtDateTime, h, normalizeKey, phoneHref, plural } from "../dom.js";
import { ALERT_STATES, LEVELS, SOURCES, levelBadge, levelMeter, tag } from "../labels.js";
import { byUrgency, isLate, isOpenAlert } from "../rules.js";
import { select as selectItem, state } from "../store.js";
import { PHONE_PATTERN, PHONE_TITLE, act, datalist, empty, field, input, modal, press, select as selectField, textarea } from "../ui.js";
import { facts, markSelected, mountView, section, segmented } from "./common.js";

const FILTERS = [["vigentes", "Vigentes"], ["vencidas", "Con reporte vencido"], ["todas", "Todas"]];

export function openNewAlert() {
  const level = selectField("level", Object.entries(LEVELS));
  const source = selectField("source", Object.entries(SOURCES));
  const muni = input("municipality", { required: true, maxlength: 80, list: "dl-muni" });
  const contactName = input("contact_name", { maxlength: 80 });
  const contactPhone = input("contact_phone", { type: "tel", pattern: PHONE_PATTERN, title: PHONE_TITLE });
  const contact = h("div", { class: "form-grid" },
    field("Contacto en el municipio", contactName), field("Teléfono de contacto", contactPhone));
  // Regla del servidor: el aviso municipal exige contacto; el de APA no lo lleva.
  const syncContact = () => {
    const needed = source.value === "municipio";
    contact.hidden = !needed;
    for (const el of [contactName, contactPhone]) { el.disabled = !needed; el.required = needed; }
  };
  source.addEventListener("change", syncContact);
  syncContact();
  const body = h("div", { class: "form-grid" },
    field("Nivel de alerta", level),
    field("Origen del aviso", source, "APA o el propio municipio."),
    field("Municipio", muni),
    datalist("dl-muni", state.meta.municipalities),
    field("Resumen de la situación", textarea("summary", { required: true, maxlength: 500 })),
    contact);
  modal({
    title: "Registrar alerta",
    intro: "Queda pendiente hasta que el Nodo 00 la verifique con APA y Policía.",
    body, submitLabel: "Registrar alerta",
    onSubmit: (f) => {
      const payload = Object.fromEntries(["level", "source", "municipality", "summary"].map((k) => [k, f.get(k)]));
      for (const k of ["contact_name", "contact_phone"]) if (f.get(k) !== null && String(f.get(k)).trim()) payload[k] = f.get(k);
      return act(() => api.registerAlert(payload), (a) => `Alerta ${a.code} registrada.`);
    },
  });
}

function matches(a) {
  const q = normalizeKey(state.filters.alertQuery);
  if (q && !normalizeKey(`${a.municipality} ${a.code} ${a.summary}`).includes(q)) return false;
  const f = state.filters.alerts;
  return f === "todas" || (f === "vencidas" ? isLate(a) : isOpenAlert(a));
}

function alertRow(a) {
  const note = a.state === "pendiente_verificacion"
    ? `APA ${a.apa_verified_at ? "verificó" : "sin verificar"}, Policía ${a.police_verified_at ? "verificó" : "sin verificar"}`
    : a.state === "activa" ? (a.center_informed_at ? "Centro de Operaciones informado" : "Centro de Operaciones sin informar") : "";
  return h("button", { type: "button", class: "row alert-row", dataset: { kind: "alert", id: a.id }, "aria-selected": "false",
    onclick: () => selectItem("alert", a.id) },
  levelBadge(a.level),
  h("span", { class: "row-main" }, h("strong", {}, a.municipality), h("span", { class: "muted" }, a.code)),
  h("span", { class: "row-state" }, tag(ALERT_STATES[a.state], isLate(a) ? "bad" : a.state === "activa" ? "ok" : "neutral"),
    note ? h("span", { class: "muted small" }, note) : null),
  a.state === "activa" ? clockEl(a) : h("span", { class: "muted small" }, a.closed_at ? `Cerrada ${fmtDateTime(a.closed_at)}` : ""));
}

export function renderAlerts(container) {
  const entry = mountView(container, "alertas", (root) => {
    const search = h("input", { type: "search", class: "search", placeholder: "Buscar municipio o código", "aria-label": "Buscar alerta",
      oninput: (e) => { state.filters.alertQuery = e.target.value; render(); } });
    const seg = segmented("Filtro de alertas", FILTERS, () => state.filters.alerts, (v) => { state.filters.alerts = v; render(); });
    const create = state.me.role === "nodo_07"
      ? h("button", { type: "button", class: "btn primary", onclick: openNewAlert }, "Registrar alerta") : null;
    const list = h("div", { class: "rows", role: "list" });
    root.append(h("header", { class: "view-head" }, h("h1", {}, "Alertas"), create),
      h("div", { class: "toolbar" }, search, seg.el), list);
    const render = () => { entry.sig = ""; renderAlerts(container); };
    return { seg, list };
  });
  const { seg, list } = entry.refs;
  seg.sync();
  const items = state.alerts.filter(matches).sort(byUrgency);
  const sig = items.map((a) => `${a.id}:${a.version}`).join(",") + state.filters.alerts;
  if (sig !== entry.sig) {
    entry.sig = sig;
    list.replaceChildren(...(items.length ? items.map(alertRow)
      : [empty("No hay alertas para mostrar", "Cambie el filtro o registre una alerta nueva.")]));
  }
  markSelected(list);
}

function verifyDialog(a) {
  const source = selectField("source", [["apa", "APA"], ["policia", "Policía"]]);
  const confirmed = selectField("confirmed", [["true", "Confirma la alerta"], ["false", "No la confirma (descartar)"]]);
  modal({
    title: "Registrar verificación", intro: `Alerta ${a.code}, ${a.municipality}. Se activa cuando confirman APA y Policía.`,
    body: h("div", { class: "form-grid" }, field("Quién verificó", source), field("Resultado", confirmed),
      field("Observación", textarea("note", { maxlength: 300 }))),
    submitLabel: "Registrar verificación",
    onSubmit: (f) => {
      const body = { source: f.get("source"), confirmed: f.get("confirmed") === "true", expected_version: a.version };
      if (String(f.get("note")).trim()) body.note = f.get("note");
      return act(() => api.verifyAlert(a.id, body), "Verificación registrada.");
    },
  });
}

function reportDialog(a) {
  const lowered = h("input", { type: "checkbox", name: "alert_lowered" });
  modal({
    title: "Registrar reporte de estado", intro: `Reporte del municipio de ${a.municipality}. El próximo vence en ${a.report_interval_hours} h.`,
    body: h("div", { class: "form-grid" },
      field("Estado informado por el municipio", textarea("municipal_status", { required: true, maxlength: 500 })),
      h("label", { class: "check" }, lowered, "El municipio informa que la alerta bajó (cierra la alerta)")),
    submitLabel: "Registrar reporte",
    onSubmit: (f) => act(() => api.reportAlert(a.id, {
      municipal_status: f.get("municipal_status"), alert_lowered: f.get("alert_lowered") === "on", expected_version: a.version,
    }), "Reporte registrado."),
  });
}

function levelDialog(a) {
  const level = selectField("level", Object.entries(LEVELS).filter(([k]) => k !== a.level));
  modal({
    title: "Cambiar nivel de alerta", intro: `Nivel actual: ${LEVELS[a.level]}. El plazo de reporte se recalcula.`,
    body: h("div", { class: "form-grid" }, field("Nuevo nivel", level), field("Motivo del cambio", textarea("note", { required: true, maxlength: 300 }))),
    submitLabel: "Cambiar nivel",
    onSubmit: (f) => act(() => api.changeLevel(a.id, { level: f.get("level"), note: f.get("note"), expected_version: a.version }), "Nivel actualizado."),
  });
}

const check = (done, label, when) => h("li", { class: done ? "step done" : "step" },
  h("span", { class: "step-dot", "aria-hidden": "true" }), h("span", {}, label), h("span", { class: "muted small" }, done ? fmtDateTime(when) : "Pendiente"));

/** Contenido del panel de detalle. `a` incluye `reports` (GET /alerts/{id}). */
export function alertDetail(a) {
  const role = state.me.role;
  const actions = [];
  if (role === "nodo_00" && a.state === "pendiente_verificacion")
    actions.push(h("button", { type: "button", class: "btn primary", onclick: () => verifyDialog(a) }, "Registrar verificación"));
  if (role === "nodo_00" && a.state === "activa" && !a.center_informed_at)
    actions.push(h("button", { type: "button", class: "btn primary", onclick: (e) =>
      press(e.currentTarget, () => api.informCenter(a.id, a.version), "Centro de Operaciones informado.") }, "Informar al Centro de Operaciones"));
  if (role === "nodo_07" && a.state === "activa")
    actions.push(h("button", { type: "button", class: "btn primary", onclick: () => reportDialog(a) }, "Registrar reporte"),
      h("button", { type: "button", class: "btn", onclick: () => levelDialog(a) }, "Cambiar nivel"));

  const reports = a.reports ?? [];
  const body = [
    actions.length ? h("div", { class: "actions" }, actions) : null,
    a.state === "activa" ? section("Reloj del reporte", clockEl(a)) : null,
    section("Verificación",
      h("ol", { class: "steps" },
        check(Boolean(a.apa_verified_at), "Verificada por APA", a.apa_verified_at),
        check(Boolean(a.police_verified_at), "Verificada por Policía", a.police_verified_at),
        check(Boolean(a.center_informed_at), "Centro de Operaciones informado", a.center_informed_at))),
    section("Situación", h("p", { class: "prose" }, a.summary),
      facts([["Origen", SOURCES[a.source]], ["Registrada", fmtDateTime(a.created_at)], ["Por", a.created_by],
        ["Frecuencia de reporte", a.report_interval_hours ? `Cada ${a.report_interval_hours} h` : ""],
        ["Contacto", a.contact_name], ["Teléfono", a.contact_phone ? h("a", { href: phoneHref(a.contact_phone) }, a.contact_phone) : ""]])),
    section(plural(reports.length, "reporte de estado", "reportes de estado"),
      reports.length ? h("ul", { class: "timeline" }, [...reports].reverse().map((r) =>
        h("li", {}, h("span", { class: "muted small" }, `${fmtDateTime(r.reported_at)}, ${r.reported_by}, nivel ${LEVELS[r.level_at_report] ?? r.level_at_report}`),
          h("p", {}, r.municipal_status), r.alert_lowered ? tag("Alerta bajada", "ok") : null)))
        : h("p", { class: "muted" }, "Todavía no hay reportes.")),
  ];
  return {
    title: a.municipality, subtitle: a.code,
    tags: [levelBadge(a.level), tag(ALERT_STATES[a.state], a.state === "activa" ? "ok" : "neutral"), isLate(a) ? tag("Reporte vencido", "bad") : null],
    body,
  };
}

export { levelMeter };
