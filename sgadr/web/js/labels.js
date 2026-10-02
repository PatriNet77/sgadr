// Vocabulario de la interfaz. Los textos salen del documento de circuitos; una acción se llama
// igual en el botón, en el formulario y en el aviso de confirmación.
import { h } from "./dom.js";

export const LEVELS = { amarillo: "Amarillo", naranja: "Naranja", rojo: "Rojo" };

export const ALERT_STATES = {
  pendiente_verificacion: "Pendiente de verificación",
  activa: "Activa",
  cerrada: "Cerrada",
  descartada: "Descartada",
};

export const DEMAND_STATES = {
  recibida: "Recibida",
  verificada: "Verificada",
  pendiente_autorizacion: "Pendiente de autorización",
  autorizada: "Autorizada",
  asignada: "Asignada",
  en_ejecucion: "En ejecución",
  respondida: "Respondida",
  cerrada: "Cerrada",
  rechazada: "Rechazada",
  recursos_agotados: "Recursos agotados",
};

// Tramo principal del circuito de demandas (secuencia real, en este orden).
export const PIPELINE = [
  "recibida", "verificada", "pendiente_autorizacion", "autorizada", "asignada", "en_ejecucion", "respondida",
];

export const SOURCES = { apa: "APA", municipio: "Municipio" };
export const VERIFIERS = { apa: "APA", policia: "Policía" };

export const TABS = { tablero: "Situación", alertas: "Alertas", demandas: "Demandas", bitacora: "Bitácora", usuarios: "Usuarios" };

export const ROLES = {
  nodo_07: { label: "Nodo 07 (Información)", tabs: ["tablero", "alertas", "demandas"] },
  nodo_00: { label: "Nodo 00 (Recursos provinciales)", tabs: ["tablero", "alertas", "demandas"] },
  comite: { label: "Comité de Emergencia Provincial", tabs: ["tablero", "alertas", "demandas", "bitacora"] },
  monitoreo: { label: "Centro de Monitoreo", tabs: ["tablero", "alertas", "demandas", "bitacora"] },
  area: { label: "Área provincial", tabs: ["tablero", "demandas"] },
  admin: { label: "Administración del sistema", tabs: ["usuarios"] },
};

// Nombre de cada acción sobre una demanda, según el estado al que lleva.
export const ACTION_LABELS = {
  verificada: "Confirmar datos",
  pendiente_autorizacion: "Solicitar autorización al Comité",
  autorizada: "Autorizar",
  asignada: "Asignar área",
  en_ejecucion: "Iniciar respuesta",
  respondida: "Informar respuesta",
  cerrada: "Cerrar demanda",
  rechazada: "Rechazar",
  recursos_agotados: "Informar recursos agotados",
};

export const ACTION_LOG = {
  register: "Demanda registrada",
  transition: "Cambio de estado de demanda",
  alert_register: "Alerta registrada",
  alert_verified: "Alerta verificada",
  alert_discarded: "Alerta descartada",
  alert_center_informed: "Centro de Operaciones informado",
  alert_report: "Reporte de estado",
  alert_level_change: "Cambio de nivel",
  alert_report_overdue: "Reporte vencido",
  login: "Ingreso",
  login_failed: "Ingreso fallido",
  logout: "Salida",
  user_created: "Usuario creado",
  user_deactivated: "Usuario dado de baja",
  user_reactivated: "Usuario reactivado",
  password_reset: "Contraseña restablecida",
  password_changed: "Contraseña cambiada",
};

/** Tres barras de señal: 1 llena = amarillo, 2 = naranja, 3 = rojo. No depende solo del color. */
export function levelMeter(level) {
  return h("span", { class: "lvl", dataset: { level }, role: "img", "aria-label": `Nivel ${LEVELS[level] ?? level}` },
    h("i"), h("i"), h("i"));
}

export const levelBadge = (level) =>
  h("span", { class: "lvl-badge", dataset: { level } }, levelMeter(level), h("span", { class: "lvl-name" }, LEVELS[level] ?? level));

export const tag = (text, tone = "neutral") => h("span", { class: `tag ${tone}` }, text);
