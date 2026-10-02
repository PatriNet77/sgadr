"""Servidor HTTP local basado en wsgiref (solo biblioteca estándar).

Es multihilo, con timeout por conexión y TLS opcional. Para exposición a internet
o cargas altas, publique el mismo objeto WSGI (`sgadr.app.build_app`) tras un proxy
inverso con TLS (nginx, Apache, IIS) o un servidor WSGI dedicado.
"""

from __future__ import annotations

import logging
import ssl
from socketserver import ThreadingMixIn
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

log = logging.getLogger("sgadr.server")

CONNECTION_TIMEOUT_S = 15  # corta clientes lentos (slowloris) y conexiones colgadas


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    request_queue_size = 64


class _Handler(WSGIRequestHandler):
    timeout = CONNECTION_TIMEOUT_S

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - firma de la base
        # Log de acceso por `logging`; la cabecera Authorization nunca se registra.
        log.info("%s %s", self.address_string(), format % args)


def build_server(
    app: Any,
    host: str,
    port: int,
    *,
    certfile: str | None = None,
    keyfile: str | None = None,
) -> WSGIServer:
    """Crea el servidor; si hay certificado, envuelve el socket en TLS >= 1.2."""
    server = make_server(host, port, app, server_class=ThreadedWSGIServer, handler_class=_Handler)
    if certfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile, keyfile)
        # Handshake diferido: se hace en el hilo de cada conexión y no bloquea el accept().
        server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    return server
