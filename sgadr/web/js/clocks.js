// El reloj del reporte: barra que se llena hasta el próximo reporte de estado del municipio
// (cada 12 h en amarillo, 6 h en naranja y rojo) y pasa a rayado rojo cuando vence.
import { duration, h } from "./dom.js";
import { serverNow } from "./store.js";

export function clockEl(alert) {
  return h("div", {
    class: "clock",
    dataset: { due: alert.next_report_due_at, hours: alert.report_interval_hours, level: alert.level },
  },
  h("div", { class: "clock-track", "aria-hidden": "true" }, h("div", { class: "clock-fill" })),
  h("p", { class: "clock-text" }, ""));
}

/** Recalcula todos los relojes visibles con la hora del servidor (no la del equipo). */
export function updateClocks(root = document) {
  const now = serverNow().getTime();
  for (const el of root.querySelectorAll(".clock[data-due]")) {
    const span = Number(el.dataset.hours) * 3_600_000;
    const remaining = Date.parse(el.dataset.due) - now;
    const progress = Math.min(1, Math.max(0, 1 - remaining / span));
    el.dataset.status = remaining <= 0 ? "late" : remaining < span * 0.25 ? "soon" : "ok";
    el.style.setProperty("--p", progress.toFixed(3));
    el.querySelector(".clock-text").textContent =
      remaining <= 0 ? `Reporte vencido hace ${duration(-remaining)}` : `Próximo reporte en ${duration(remaining)}`;
  }
}
