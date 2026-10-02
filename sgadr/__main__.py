"""Línea de comandos: python -m sgadr {serve,create-user,deactivate-user,verify-audit}."""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import signal
import smtplib
import sys
from collections.abc import Sequence
from types import FrameType

from .app import build_app
from .domain import DomainError, Role
from .mailer import EmailNotifier, MailConfigError, SmtpConfig
from .reminders import ChainedNotifier, ReminderWorker, log_notifier
from .server import build_server

log = logging.getLogger("sgadr")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sgadr", description="Sistema de Gestión de Alertas, Demandas y Respuestas")
    p.add_argument("--db", default=os.environ.get("SGADR_DB", "sgadr.db"),
                   help="ruta de la base SQLite (env SGADR_DB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="inicia el servidor HTTP")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--cert", help="certificado TLS (PEM)")
    s.add_argument("--key", help="clave privada TLS (PEM)")
    s.add_argument("--reminder-interval", type=float, default=60.0,
                   help="segundos entre controles de reportes vencidos (por defecto 60)")

    c = sub.add_parser("create-user", help="crea un usuario (pide la contraseña por teclado)")
    c.add_argument("username")
    c.add_argument("--role", required=True, choices=[r.value for r in Role])
    c.add_argument("--area", help="obligatoria para el rol 'area'")

    d = sub.add_parser("deactivate-user", help="da de baja un usuario y revoca sus sesiones")
    d.add_argument("username")

    sub.add_parser("test-mail", help="envía un correo de prueba con la configuración SGADR_SMTP_*")
    sub.add_parser("verify-audit", help="verifica la integridad de la bitácora encadenada")
    return p


def _serve(args: argparse.Namespace) -> int:
    if bool(args.cert) != bool(args.key):
        print("--cert y --key deben indicarse juntos.", file=sys.stderr)
        return 2
    app = build_app(args.db, hsts=bool(args.cert))
    server = build_server(app.api, args.host, args.port, certfile=args.cert, keyfile=args.key)
    try:
        mail = SmtpConfig.from_env(os.environ)
    except MailConfigError as exc:
        print(f"Configuración de correo inválida: {exc}", file=sys.stderr)
        return 2
    if mail is None:
        log.warning("Correo no configurado (SGADR_SMTP_HOST): los reportes vencidos solo se registran en el log.")
        notifier = ChainedNotifier(log_notifier)
    else:
        log.info("Reportes vencidos: aviso por correo a %s", ", ".join(mail.recipients))
        notifier = ChainedNotifier(log_notifier, EmailNotifier(mail))
    reminders = ReminderWorker(app.alerts, notifier, interval_s=args.reminder_interval)

    def _stop(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt  # SIGTERM/SIGINT -> cierre ordenado

    signal.signal(signal.SIGTERM, _stop)
    scheme = "https" if args.cert else "http"
    log.info("SGADR escuchando en %s://%s:%d", scheme, args.host, args.port)
    reminders.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Cierre solicitado.")
    finally:
        reminders.stop()
        server.server_close()
        app.store.close()
    return 0


def _test_mail() -> int:
    try:
        config = SmtpConfig.from_env(os.environ)
        if config is None:
            print("Defina SGADR_SMTP_HOST (y los demás SGADR_SMTP_*) para probar el correo.", file=sys.stderr)
            return 2
        EmailNotifier(config).send_test()
    except (MailConfigError, OSError, smtplib.SMTPException) as exc:
        print(f"No se pudo enviar el correo de prueba: {exc}", file=sys.stderr)
        return 1
    print(f"Correo de prueba enviado a {', '.join(config.recipients)}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        if args.cmd == "serve":
            return _serve(args)
        if args.cmd == "test-mail":
            return _test_mail()
        app = build_app(args.db)
        try:
            if args.cmd == "create-user":
                pwd = getpass.getpass("Contraseña (mín. 12 caracteres): ")
                if pwd != getpass.getpass("Repetir contraseña: "):
                    print("Las contraseñas no coinciden.", file=sys.stderr)
                    return 2
                app.auth.create_user(args.username, pwd, Role(args.role), args.area)
                print(f"Usuario '{args.username}' creado.")
            elif args.cmd == "deactivate-user":
                app.auth.deactivate_user(args.username)
                print(f"Usuario '{args.username}' dado de baja.")
            else:  # verify-audit
                valid = app.demands.verify_audit()
                print("Bitácora ÍNTEGRA." if valid else "ALERTA: bitácora ALTERADA.")
                return 0 if valid else 1
        finally:
            app.store.close()
    except DomainError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error de E/S: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
