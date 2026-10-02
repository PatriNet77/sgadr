// Pantalla de ingreso.
import { api, session } from "../api.js";
import { h } from "../dom.js";
import { field, input } from "../ui.js";

export function renderLogin(container, onDone) {
  const error = h("p", { class: "form-error", role: "alert", hidden: true });
  const submit = h("button", { type: "submit", class: "btn primary wide" }, "Ingresar");
  const form = h("form", { class: "login-card", onsubmit: async (e) => {
    e.preventDefault();
    error.hidden = true; submit.disabled = true;
    const f = new FormData(form);
    try {
      const r = await api.login(f.get("username"), f.get("password"));
      session.set?.(r.token);
      await onDone();
    } catch (err) {
      error.textContent = err.message || "No se pudo ingresar."; error.hidden = false;
    } finally { submit.disabled = false; }
  } },
  h("h1", {}, "Gestión de alertas y demandas"), h("p", { class: "muted" }, "Emergencia por ENOS, Provincia del Chaco"),
  field("Usuario", input("username", { required: true, autocapitalize: "none", spellcheck: "false", autocomplete: "username" })),
  field("Contraseña", input("password", { type: "password", required: true, autocomplete: "current-password" })),
  error, submit);
  container.replaceChildren(h("main", { class: "login" }, form));
  form.querySelector("input")?.focus();
}
