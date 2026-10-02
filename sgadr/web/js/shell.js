// Estructura general: barra lateral con navegación y estado, y área de contenido.
import { api, session } from "./api.js";
import { fmtClock, h } from "./dom.js";
import { ROLES, TABS } from "./labels.js";
import { isLate, isOpenAlert, isOpenDemand } from "./rules.js";
import { serverNow, setView, state } from "./store.js";
import { openChangePassword } from "./views/account.js";

const THEME_KEY = "sgadr.theme";
const safe = (fn) => { try { return fn(); } catch { return null; } };

export function applyTheme(mode) {
  if (mode) document.documentElement.dataset.theme = mode; else delete document.documentElement.dataset.theme;
}
export const initTheme = () => applyTheme(safe(() => localStorage.getItem(THEME_KEY)));

function toggleTheme() {
  const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const next = dark ? "light" : "dark";
  applyTheme(next);
  safe(() => localStorage.setItem(THEME_KEY, next));
}

export function buildShell(root, onLogout) {
  const nav = h("nav", { class: "nav", "aria-label": "Secciones" });
  const clock = h("p", { class: "now", "aria-hidden": "true" });
  const sync = h("p", { class: "sync", role: "status" });
  const main = h("main", { class: "main", id: "main" });
  const drawer = h("aside", { class: "drawer", hidden: true, "aria-live": "off" });
  const role = state.me.role;
  const chip = h("div", { class: "who" },
    h("p", { class: "who-role" }, ROLES[role].label), h("p", { class: "who-user" }, state.me.area ? `${state.me.username}, ${state.me.area}` : state.me.username));
  const rail = h("header", { class: "rail" },
    h("p", { class: "brand" }, "Alertas y demandas"), chip, nav, clock, sync,
    h("div", { class: "rail-foot" },
      h("button", { type: "button", class: "btn ghost", onclick: () => openChangePassword() }, "Cambiar contraseña"),
      h("button", { type: "button", class: "btn ghost", onclick: toggleTheme }, "Cambiar tema"),
      h("button", { type: "button", class: "btn ghost", onclick: async () => { try { await api.logout(); } catch { /* ya vencida */ } session.clear(); onLogout(); } }, "Salir")));
  root.dataset.role = role;
  root.replaceChildren(h("a", { class: "skip", href: "#main" }, "Ir al contenido"), rail, main, drawer);
  return { nav, clock, sync, main, drawer };
}

export function updateNav(nav) {
  const counts = {
    alertas: state.alerts.filter(isOpenAlert).length,
    demandas: state.demands.filter(isOpenDemand).length,
  };
  const late = state.alerts.filter(isLate).length;
  nav.replaceChildren(...ROLES[state.me.role].tabs.map((tab) => h("button", { type: "button", class: "nav-btn", "aria-current": state.view === tab ? "page" : null,
    onclick: () => setView(tab) }, h("span", {}, TABS[tab]),
  counts[tab] !== undefined ? h("span", { class: tab === "alertas" && late ? "count bad" : "count", "aria-label": `${counts[tab]} abiertas${tab === "alertas" && late ? `, ${late} con reporte vencido` : ""}` }, counts[tab]) : null)));
}

export function updateStatus(clock, sync) {
  clock.textContent = fmtClock(serverNow());
  sync.className = state.online ? "sync" : "sync off";
  sync.textContent = !state.online ? "Sin conexión con el servidor. Mostrando los últimos datos."
    : state.lastSync ? `Actualizado ${fmtClock(state.lastSync)}` : "Conectando…";
}
