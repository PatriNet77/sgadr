// Panel de detalle lateral. Reconstruye solo cuando cambia el registro (clave tipo:id:versión).
import { api } from "./api.js";
import { updateClocks } from "./clocks.js";
import { h } from "./dom.js";
import { closeDetail, state } from "./store.js";
import { alertDetail } from "./views/alerts.js";
import { demandDetail } from "./views/demands.js";

let shownKey = "";
let reportsCache = { id: 0, version: 0, data: null };

async function fullAlert(a) {
  if (reportsCache.id === a.id && reportsCache.version === a.version) return reportsCache.data;
  const data = await api.alert(a.id);
  reportsCache = { id: a.id, version: a.version, data };
  return data;
}

export async function renderDrawer(host) {
  const sel = state.selected;
  const item = sel && (sel.kind === "alert" ? state.alerts : state.demands).find((x) => x.id === sel.id);
  if (!item) {
    if (shownKey) { shownKey = ""; host.replaceChildren(); host.hidden = true; document.body.classList.remove("has-drawer"); }
    return;
  }
  const key = `${sel.kind}:${item.id}:${item.version}:${state.me.role}`;
  if (key === shownKey) return;
  const fresh = !shownKey.startsWith(`${sel.kind}:${item.id}:`);
  let content;
  try {
    content = sel.kind === "alert" ? alertDetail(await fullAlert(item)) : demandDetail(item);
  } catch {
    return; // sin conexión: se conserva lo que ya se ve
  }
  if (!state.selected || state.selected.id !== item.id) return; // se cerró o cambió mientras cargaba
  shownKey = key;
  const close = h("button", { type: "button", class: "btn icon", "aria-label": "Cerrar detalle", onclick: closeDetail }, "Cerrar");
  host.replaceChildren(
    h("header", { class: "drawer-head" }, h("div", {}, h("h2", { id: "drawer-title" }, content.title), h("p", { class: "muted" }, content.subtitle),
      h("div", { class: "tags" }, content.tags)), close),
    h("div", { class: "drawer-body" }, content.body));
  updateClocks(host);
  host.hidden = false;
  host.setAttribute("aria-labelledby", "drawer-title");
  document.body.classList.add("has-drawer");
  if (fresh) close.focus();
}
