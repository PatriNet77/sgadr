// Componentes compartidos: avisos, diálogos con formulario y campos.
import { ApiError } from "./api.js";
import { h } from "./dom.js";
import { refresh } from "./store.js";

/** Error ya informado a la persona: el diálogo se cierra sin mostrar otro mensaje. */
export class Handled extends Error {}

export function toast(message, tone = "ok") {
  const host = document.getElementById("toasts");
  if (!host) return;
  const item = h("div", { class: `toast ${tone}` }, message);
  host.append(item);
  setTimeout(() => item.remove(), tone === "ok" ? 5000 : 10000);
}

let counter = 0;
const nextId = () => `f${++counter}`;

export function field(label, control, hint) {
  const id = nextId();
  control.id = id;
  const wrap = h("div", { class: "field" }, h("label", { for: id }, label), control);
  if (hint) {
    const hintId = `${id}-hint`;
    control.setAttribute("aria-describedby", hintId);
    wrap.append(h("p", { class: "hint", id: hintId }, hint));
  }
  return wrap;
}

export const input = (name, attrs = {}) => h("input", { name, autocomplete: "off", ...attrs });
export const textarea = (name, attrs = {}) => h("textarea", { name, rows: 3, ...attrs });
export const select = (name, options, attrs = {}) =>
  h("select", { name, ...attrs }, options.map(([value, label]) => h("option", { value }, label)));

/**
 * Diálogo modal con formulario. `onSubmit(FormData)` puede lanzar un error: se muestra dentro del
 * diálogo y este permanece abierto para corregir. Los campos deshabilitados no se envían ni validan.
 */
export function modal({ title, intro, body, submitLabel, tone = "primary", onSubmit, forced = false, secondary = null }) {
  const opener = document.activeElement;
  const error = h("p", { class: "form-error", role: "alert", hidden: true });
  const submit = h("button", { type: "submit", class: `btn ${tone}` }, submitLabel);
  const dialog = h("dialog", { class: "dlg", "aria-labelledby": "dlg-title" });
  const cancel = h("button", { type: "button", class: "btn", onclick: () => dialog.close() }, "Cancelar");

  const form = h("form", {
    method: "dialog",
    onsubmit: async (event) => {
      event.preventDefault();
      error.hidden = true;
      submit.disabled = true;
      try {
        await onSubmit(new FormData(form));
        dialog.close();
      } catch (e) {
        if (e instanceof Handled) dialog.close();
        else {
          error.textContent = e instanceof ApiError || e instanceof Error ? e.message : "No se pudo completar la acción.";
          error.hidden = false;
        }
      } finally {
        submit.disabled = false;
      }
    },
  },
  h("header", { class: "dlg-head" }, h("h2", { id: "dlg-title" }, title), intro ? h("p", { class: "muted" }, intro) : null),
  h("div", { class: "dlg-body" }, body),
  error,
  h("footer", { class: "dlg-foot" }, forced ? secondary && h("button", { type: "button", class: "btn", onclick: () => { dialog.close(); secondary.onClick(); } }, secondary.label) : cancel, submit));

  dialog.append(form);
  // Diálogo obligatorio (cambio de clave temporal): ni Esc ni clic fuera lo cierran.
  if (forced) dialog.addEventListener("cancel", (e) => e.preventDefault());
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
  });
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector("input:not([disabled]), textarea:not([disabled]), select:not([disabled])")?.focus();
  return dialog;
}

/**
 * Ejecuta una acción contra la API, avisa el resultado y recarga los datos.
 * Ante un conflicto de versión (otra persona modificó el registro) recarga y lo informa.
 */
export async function act(fn, successMessage) {
  try {
    const result = await fn();
    toast(typeof successMessage === "function" ? successMessage(result) : successMessage);
    return result;
  } catch (e) {
    if (e instanceof ApiError && e.code === "concurrency_conflict") {
      toast("Otra persona modificó este registro. Se cargó la versión actual: revísela y repita la acción.", "warn");
      throw new Handled();
    }
    throw e;
  } finally {
    await refresh().catch(() => {});
  }
}

/** Botón de acción directa: se deshabilita mientras corre y muestra el error como aviso. */
export async function press(button, fn, successMessage) {
  button.disabled = true;
  try {
    return await act(fn, successMessage);
  } catch (e) {
    if (!(e instanceof Handled)) toast(e.message, "error");
    return undefined;
  } finally {
    button.disabled = false;
  }
}

// Coincide con el formato que valida el servidor: +54 362 4000000, (0362) 400-0000, etc.
export const PHONE_PATTERN = "\\+?[0-9][0-9 \\(\\)\\-]{5,19}";
export const PHONE_TITLE = "Teléfono con característica. Ejemplo: +54 362 4000000";

export const datalist = (id, values) => h("datalist", { id }, values.map((value) => h("option", { value })));

export const empty = (title, text, action) =>
  h("div", { class: "empty" }, h("p", { class: "empty-title" }, title), text ? h("p", { class: "muted" }, text) : null, action ?? null);
