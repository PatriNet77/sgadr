// Utilidades de DOM y formato. Todo texto entra como nodo de texto: nunca se usa innerHTML,
// por lo que los datos del servidor no pueden inyectar marcado (defensa adicional a la CSP).

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const DATETIME = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});
const CLOCK = new Intl.DateTimeFormat("es-AR", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});

export const fmtDateTime = (iso) => (iso ? DATETIME.format(new Date(iso)) : "—");
export const fmtClock = (date) => CLOCK.format(date);

/** Duración legible: "3 h 12 min", "45 min", "2 d 4 h". */
export function duration(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 1) return "menos de 1 min";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  if (hours < 48) return rest ? `${hours} h ${rest} min` : `${hours} h`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

export function ago(ms) {
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "ahora";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `hace ${hours} h` : `hace ${Math.floor(hours / 24)} d`;
}

export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** Misma idea que normalize_key del servidor: sin tildes, minúsculas, espacios colapsados. */
export const normalizeKey = (text) =>
  String(text ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");

/** Enlace tel: solo con dígitos y '+', para que ningún dato del servidor arme otro tipo de URL. */
export const phoneHref = (phone) => `tel:${String(phone).replace(/[^0-9+]/g, "")}`;
