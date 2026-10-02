// Soporte común de las vistas: montaje único (conserva campos y foco), selección y filtros.
import { h } from "../dom.js";
import { state } from "../store.js";

const mounted = new WeakMap();

/**
 * Construye la estructura fija de una vista una sola vez (barra de filtros, buscador) y la
 * reutiliza en cada actualización: así escribir en el buscador no pierde el foco.
 */
export function mountView(container, name, build) {
  let entry = mounted.get(container);
  if (!entry || entry.name !== name) {
    container.replaceChildren();
    entry = { name, sig: "", refs: build(container) };
    mounted.set(container, entry);
  }
  return entry;
}

export function markSelected(host) {
  const selected = state.selected;
  for (const row of host.querySelectorAll("[data-id]")) {
    const isSelected = Boolean(selected) && row.dataset.kind === selected.kind && Number(row.dataset.id) === selected.id;
    row.setAttribute("aria-selected", String(isSelected));
  }
}

export function segmented(label, options, get, set) {
  const buttons = options.map(([value, text]) =>
    h("button", { type: "button", role: "radio", class: "seg-btn", onclick: () => set(value) }, text));
  const el = h("div", { class: "seg", role: "radiogroup", "aria-label": label }, buttons);
  const sync = () => options.forEach(([value], i) => buttons[i].setAttribute("aria-checked", String(get() === value)));
  return { el, sync };
}

export const section = (title, ...children) => h("section", { class: "dsec" }, h("h3", {}, title), ...children);

export function facts(pairs) {
  const rows = pairs.filter(([, value]) => value !== null && value !== undefined && value !== "");
  return h("dl", { class: "facts" }, rows.map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, value))));
}
