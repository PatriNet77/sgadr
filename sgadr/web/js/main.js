// Arranque: sesión, ingreso, sondeo periódico y composición de la interfaz.
import { session, setUnauthorizedHandler } from "./api.js";
import { updateClocks } from "./clocks.js";
import { renderDrawer } from "./drawer.js";
import { buildShell, initTheme, updateNav, updateStatus } from "./shell.js";
import { bootstrap, closeDetail, refresh, resetState, state, subscribe } from "./store.js";
import { toast } from "./ui.js";
import { renderAlerts } from "./views/alerts.js";
import { renderAudit } from "./views/audit.js";
import { renderBoard } from "./views/board.js";
import { renderDemands } from "./views/demands.js";
import { renderLogin } from "./views/login.js";
import { renderUsers } from "./views/users.js";
import { openChangePassword } from "./views/account.js";
import { api } from "./api.js";
import { h } from "./dom.js";

const root = document.getElementById("app");
const POLL_MS = 15_000;
let timers = [];
let unsubscribe = () => {};

function stop() {
  timers.forEach(clearInterval);
  timers = [];
  unsubscribe();
}

function showLogin(message) {
  stop();
  resetState();
  delete root.dataset.role;
  document.body.classList.remove("has-drawer");
  renderLogin(root, start);
  if (message) toast(message, "warn");
}

const VIEWS = { tablero: renderBoard, alertas: renderAlerts, demandas: renderDemands, bitacora: renderAudit, usuarios: renderUsers };

/** Cuenta con clave temporal: no hay interfaz operativa hasta que la persona defina la suya. */
function forceChange() {
  delete root.dataset.role;
  root.replaceChildren(h("main", { class: "login" }, h("div", { class: "login-card" },
    h("h1", {}, "Contraseña temporal"), h("p", { class: "muted" }, "Debe definir una contraseña propia para continuar."))));
  openChangePassword({
    forced: true, onDone: start,
    onExit: async () => { try { await api.logout(); } catch { /* sesión ya vencida */ } session.clear(); showLogin(); },
  });
}

async function start() {
  stop();
  if (!(await bootstrap())) { forceChange(); return; }
  const ui = buildShell(root, () => showLogin());
  let lastView = "";
  const paint = () => {
    updateNav(ui.nav);
    updateStatus(ui.clock, ui.sync);
    if (state.view !== lastView) { ui.main.replaceChildren(); lastView = state.view; }
    VIEWS[state.view](ui.main);
    updateClocks(root);
    renderDrawer(ui.drawer);
  };
  unsubscribe = subscribe(paint);
  await refresh().catch(() => {});
  paint();
  timers.push(setInterval(() => refresh().catch(() => {}), POLL_MS));
  timers.push(setInterval(() => { updateClocks(root); updateStatus(ui.clock, ui.sync); }, 1000));
}

setUnauthorizedHandler(() => { session.clear(); showLogin("La sesión venció. Ingrese de nuevo."); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) closeDetail(); });

initTheme();
(session.token ? start() : Promise.resolve(showLogin())).catch(() => showLogin());
