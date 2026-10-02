// Cambio de contraseña propio (opcional desde el menú; obligatorio con clave temporal).
import { api } from "../api.js";
import { h } from "../dom.js";
import { act, field, input, modal } from "../ui.js";

export function openChangePassword({ forced = false, onDone, onExit } = {}) {
  const body = h("div", { class: "form-grid" },
    field("Contraseña actual", input("current", { type: "password", required: true, autocomplete: "current-password" })),
    field("Contraseña nueva", input("next", { type: "password", required: true, minlength: 12, maxlength: 256, autocomplete: "new-password" }),
      "Mínimo 12 caracteres. Al cambiarla se cierran sus otras sesiones."),
    field("Repetir contraseña nueva", input("again", { type: "password", required: true, minlength: 12, maxlength: 256, autocomplete: "new-password" })));
  modal({
    title: forced ? "Cambie su contraseña temporal" : "Cambiar mi contraseña",
    intro: forced ? "Su cuenta tiene una contraseña temporal. Defina una propia para continuar." : undefined,
    body, submitLabel: "Cambiar contraseña", forced,
    secondary: forced && onExit ? { label: "Salir", onClick: onExit } : null,
    onSubmit: async (f) => {
      if (f.get("next") !== f.get("again")) throw new Error("Las contraseñas nuevas no coinciden.");
      await act(() => api.changePassword(f.get("current"), f.get("next")), "Contraseña cambiada.");
      if (onDone) await onDone();
    },
  });
}
