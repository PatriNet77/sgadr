// Consola de administración de cuentas (rol admin): altas con clave temporal, baja y restablecimiento.
import { api } from "../api.js";
import { fmtDateTime, h, plural } from "../dom.js";
import { ROLES, tag } from "../labels.js";
import { state } from "../store.js";
import { act, empty, field, input, modal, press, select as selectField } from "../ui.js";
import { mountView } from "./common.js";

const ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // sin caracteres ambiguos

/** Clave temporal aleatoria (crypto del navegador, sin sesgo de módulo). */
function generatePassword(length = 16) {
  const limit = 256 - (256 % ALPHABET.length);
  const out = [];
  while (out.length < length) {
    for (const byte of crypto.getRandomValues(new Uint8Array(length * 2))) {
      if (byte < limit && out.length < length) out.push(ALPHABET[byte % ALPHABET.length]);
    }
  }
  return out.join("");
}

/** Campo de clave temporal con botón para generarla; se muestra en claro porque hay que entregarla. */
function tempPasswordField() {
  const pwd = input("temporary_password", { type: "text", required: true, minlength: 12, maxlength: 256, spellcheck: "false", autocapitalize: "none", class: "mono-input" });
  const gen = h("button", { type: "button", class: "btn", onclick: () => { pwd.value = generatePassword(); pwd.focus(); } }, "Generar");
  const wrap = field("Contraseña temporal", pwd, "Entréguela por un canal seguro. La persona deberá cambiarla al ingresar.");
  wrap.querySelector("label").after(h("div", { class: "inline" }, pwd, gen));
  return wrap;
}

function openCreate() {
  const role = selectField("role", Object.entries(ROLES).map(([k, v]) => [k, v.label]));
  const area = selectField("area", state.meta.areas.map((a) => [a, a]));
  const areaField = field("Área provincial", area);
  const sync = () => { areaField.hidden = role.value !== "area"; area.disabled = role.value !== "area"; };
  role.addEventListener("change", sync);
  sync();
  modal({
    title: "Crear usuario", intro: "La cuenta queda activa con una contraseña temporal.",
    body: h("div", { class: "form-grid" },
      field("Usuario", input("username", { required: true, minlength: 3, maxlength: 32, pattern: "[a-z0-9._\\-]{3,32}", title: "3 a 32 caracteres: minúsculas, números, punto, guion y guion bajo" })),
      field("Rol", role), areaField, tempPasswordField()),
    submitLabel: "Crear usuario",
    onSubmit: (f) => {
      const body = { username: f.get("username"), temporary_password: f.get("temporary_password"), role: f.get("role") };
      if (f.get("role") === "area") body.area = f.get("area");
      return act(() => api.createUser(body), `Usuario ${body.username} creado.`);
    },
  });
}

function openReset(u) {
  modal({
    title: "Restablecer contraseña", intro: `Se cierran las sesiones de ${u.username}, se desbloquea la cuenta y deberá cambiar la contraseña al ingresar.`,
    body: h("div", { class: "form-grid" }, tempPasswordField()), submitLabel: "Restablecer contraseña",
    onSubmit: (f) => act(() => api.resetPassword(u.username, f.get("temporary_password")), `Contraseña de ${u.username} restablecida.`),
  });
}

function openDeactivate(u) {
  modal({
    title: "Dar de baja", intro: `${u.username} no podrá ingresar y se cierran sus sesiones. Sus registros en la bitácora se conservan.`,
    body: h("p", {}, "Puede reactivar la cuenta más adelante."), submitLabel: "Dar de baja", tone: "danger",
    onSubmit: () => act(() => api.setUserActive(u.username, false), `${u.username} dado de baja.`),
  });
}

function userRow(u) {
  const mine = u.username === state.me.username;
  const tags = [u.active ? tag("Activo", "ok") : tag("Dado de baja"), u.locked ? tag("Bloqueado por intentos", "bad") : null,
    u.must_change_password ? tag("Clave temporal", "warn") : null];
  const actions = [h("button", { type: "button", class: "btn", disabled: mine || !u.active, onclick: () => openReset(u) }, "Restablecer contraseña"),
    u.active
      ? h("button", { type: "button", class: "btn", disabled: mine, onclick: () => openDeactivate(u) }, "Dar de baja")
      : h("button", { type: "button", class: "btn", onclick: (e) => press(e.currentTarget, () => api.setUserActive(u.username, true), `${u.username} reactivado.`) }, "Reactivar")];
  return h("tr", {},
    h("th", { scope: "row" }, u.username, mine ? h("span", { class: "muted small" }, " (usted)") : null),
    h("td", {}, ROLES[u.role]?.label ?? u.role, u.area ? h("span", { class: "muted small block-line" }, u.area) : null),
    h("td", {}, h("div", { class: "tags-cell" }, tags)),
    h("td", { class: "muted small" }, fmtDateTime(u.created_at)),
    h("td", {}, h("div", { class: "actions-cell" }, actions)));
}

export function renderUsers(container) {
  const entry = mountView(container, "usuarios", (root) => {
    const body = h("tbody");
    const summary = h("p", { class: "muted" });
    root.append(h("header", { class: "view-head" }, h("h1", {}, "Usuarios"),
      h("button", { type: "button", class: "btn primary", onclick: openCreate }, "Crear usuario")),
    summary,
    h("div", { class: "table-wrap" }, h("table", { class: "log users" },
      h("thead", {}, h("tr", {}, ["Usuario", "Rol", "Estado", "Alta", "Acciones"].map((t) => h("th", { scope: "col" }, t)))), body)));
    return { body, summary };
  });
  const { body, summary } = entry.refs;
  const sig = state.users.map((u) => `${u.username}:${u.active}:${u.locked}:${u.must_change_password}`).join(",");
  if (sig === entry.sig) return;
  entry.sig = sig;
  const active = state.users.filter((u) => u.active).length;
  summary.textContent = `${plural(state.users.length, "cuenta", "cuentas")}, ${active} activas.`;
  body.replaceChildren(...(state.users.length ? state.users.map(userRow)
    : [h("tr", {}, h("td", { colspan: 5 }, empty("Sin usuarios")))]));
}

