"""Servicio de archivos estáticos de la interfaz web (solo biblioteca estándar).

Seguridad:
- Solo sirve archivos bajo `web/` con extensiones en lista blanca; sin listado de directorios.
- Rechaza recorrido de rutas ('..', separadores alternativos, bytes nulos, enlaces fuera de la raíz).
- CSP estricta: nada de scripts ni estilos en línea, nada de recursos externos.
- ETag + 304 para que los equipos operativos no vuelvan a descargar lo que no cambió.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

StartResponse = Callable[..., Any]

CONTENT_TYPES: Final[dict[str, str]] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

CSP: Final = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


class StaticFiles:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @staticmethod
    def handles(path: str) -> bool:
        return path == "/" or path.startswith("/static/")

    def _locate(self, path: str) -> Path | None:
        relative = "index.html" if path == "/" else path.removeprefix("/static/")
        if not relative or "\x00" in relative or "\\" in relative:
            return None
        if any(part in ("", ".", "..") or part.startswith(".") for part in relative.split("/")):
            return None
        candidate = (self._root / relative).resolve()
        if not candidate.is_relative_to(self._root) or not candidate.is_file():
            return None
        return candidate if candidate.suffix in CONTENT_TYPES else None

    def serve(self, environ: dict[str, Any], start_response: StartResponse, *, hsts: bool) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "")
        headers: list[tuple[str, str]] = [
            ("Server", "sgadr"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy", CSP),
            ("Cache-Control", "no-cache"),
        ]
        if hsts:
            headers.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))

        if method not in ("GET", "HEAD"):
            start_response("405 Method Not Allowed", [*headers, ("Allow", "GET, HEAD"), ("Content-Length", "0")])
            return [b""]
        target = self._locate(environ.get("PATH_INFO", ""))
        if target is None:
            body = b"No encontrado"
            start_response("404 Not Found", [*headers, ("Content-Type", "text/plain; charset=utf-8"),
                                             ("Content-Length", str(len(body)))])
            return [body if method == "GET" else b""]

        data = target.read_bytes()
        etag = f'"{hashlib.sha256(data).hexdigest()[:16]}"'
        headers += [("ETag", etag), ("Content-Type", CONTENT_TYPES[target.suffix])]
        if environ.get("HTTP_IF_NONE_MATCH") == etag:
            start_response("304 Not Modified", headers)
            return [b""]
        start_response("200 OK", [*headers, ("Content-Length", str(len(data)))])
        return [data if method == "GET" else b""]
