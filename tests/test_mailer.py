"""Pruebas del aviso por correo: configuración, contenido, reintentos y un SMTP real local."""

from __future__ import annotations

import logging
import socket
import threading
import unittest
from email import message_from_bytes
from typing import Any

from sgadr.mailer import DEFAULT_RECIPIENT, EmailNotifier, MailConfigError, SmtpConfig, build_message
from sgadr.reminders import ChainedNotifier, ReminderWorker

ALERT = {"code": "ALERTA-2026-0003", "municipality": "Fontana", "level": "rojo", "overdue_minutes": 155,
         "contact_name": "Luis Paz", "contact_phone": "+54 362 4111111"}
BASE = {"SGADR_SMTP_HOST": "smtp.gmail.com", "SGADR_SMTP_USER": "sgadr@example.org", "SGADR_SMTP_PASSWORD": "app-password-xyz"}


class ConfigTests(unittest.TestCase):
    def test_not_configured_returns_none(self) -> None:
        self.assertIsNone(SmtpConfig.from_env({}))

    def test_defaults_target_monitoring_center_with_starttls(self) -> None:
        cfg = SmtpConfig.from_env(BASE)
        assert cfg is not None
        self.assertEqual((cfg.port, cfg.security, cfg.sender), (587, "starttls", "sgadr@example.org"))
        self.assertEqual(cfg.recipients, (DEFAULT_RECIPIENT,))
        self.assertEqual(DEFAULT_RECIPIENT, "centrodemonitoreochaco@gmail.com")

    def test_ssl_default_port_and_custom_recipients(self) -> None:
        cfg = SmtpConfig.from_env({**BASE, "SGADR_SMTP_SECURITY": "ssl", "SGADR_SMTP_TO": "a@x.org, b@y.org"})
        assert cfg is not None
        self.assertEqual((cfg.port, cfg.recipients), (465, ("a@x.org", "b@y.org")))

    def test_invalid_configurations(self) -> None:
        bad: list[dict[str, str]] = [
            {**BASE, "SGADR_SMTP_SECURITY": "plain"},
            {**BASE, "SGADR_SMTP_PORT": "abc"},
            {**BASE, "SGADR_SMTP_PORT": "70000"},
            {**BASE, "SGADR_SMTP_TO": "no-es-correo"},
            {**BASE, "SGADR_SMTP_TO": "a@x.org\nBcc: z@z.org"},
            {"SGADR_SMTP_HOST": "h", "SGADR_SMTP_USER": "u@x.org"},                       # usuario sin clave
            {**BASE, "SGADR_SMTP_SECURITY": "none"},                                      # credenciales sin cifrado
            {"SGADR_SMTP_HOST": "h"},                                                      # sin remitente
        ]
        for env in bad:
            with self.assertRaises(MailConfigError, msg=env):
                SmtpConfig.from_env(env)

    def test_password_not_in_repr(self) -> None:
        cfg = SmtpConfig.from_env(BASE)
        self.assertNotIn("app-password-xyz", repr(cfg))


class MessageTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = SmtpConfig.from_env(BASE)
        assert cfg is not None
        self.cfg = cfg

    def test_content_has_no_contact_data(self) -> None:
        msg = build_message(self.cfg, ALERT)
        text = msg.as_string()
        self.assertEqual(msg["To"], DEFAULT_RECIPIENT)
        self.assertIn("Fontana", msg["Subject"])
        self.assertIn("2 h 35 min", msg.get_content())
        self.assertNotIn("Luis Paz", text)
        self.assertNotIn("4111111", text)

    def test_header_injection_is_neutralised(self) -> None:
        evil = {**ALERT, "municipality": "Fontana\r\nBcc: atacante@evil.org"}
        msg = build_message(self.cfg, evil)
        self.assertNotIn("\n", msg["Subject"].replace("\n ", ""))
        self.assertIsNone(msg["Bcc"])


class NotifierTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = SmtpConfig.from_env(BASE)
        assert cfg is not None
        self.cfg = cfg
        self.sent: list[Any] = []
        self.down = True

    def transport(self, message: Any) -> None:
        if self.down:
            raise ConnectionRefusedError("sin red")
        self.sent.append(message)

    def test_failure_is_queued_and_retried_once_in_order(self) -> None:
        n = EmailNotifier(self.cfg, transport=self.transport)
        with self.assertLogs("sgadr.mailer", logging.ERROR):
            n({**ALERT, "code": "A1"})
            n({**ALERT, "code": "A2", "municipality": "Otro"})
        self.assertEqual((n.pending, len(self.sent)), (2, 0))
        with self.assertLogs("sgadr.mailer", logging.ERROR):
            self.assertEqual(n.flush(), 0)
        self.down = False
        self.assertEqual(n.flush(), 2)
        self.assertEqual((n.pending, [m["Subject"] for m in self.sent]), (0, [
            "[SGADR] Reporte vencido: Fontana (alerta rojo)", "[SGADR] Reporte vencido: Otro (alerta rojo)"]))
        self.assertEqual(n.flush(), 0)

    def test_queue_is_bounded(self) -> None:
        n = EmailNotifier(self.cfg, transport=self.transport, max_pending=3)
        with self.assertLogs("sgadr.mailer", logging.ERROR):
            for i in range(10):
                n({**ALERT, "code": f"A{i}"})
        self.assertEqual(n.pending, 3)

    def test_chain_isolates_failures_and_worker_flushes(self) -> None:
        calls: list[str] = []

        def boom(_: dict[str, Any]) -> None:
            raise RuntimeError("canal caído")

        mail = EmailNotifier(self.cfg, transport=self.transport)
        chain = ChainedNotifier(boom, lambda a: calls.append(a["code"]), mail)
        with self.assertLogs(level=logging.ERROR):
            chain(dict(ALERT))
        self.assertEqual((calls, mail.pending), (["ALERTA-2026-0003"], 1))

        class NoAlerts:
            def flag_overdue(self) -> list[dict[str, Any]]:
                return []

        self.down = False
        ReminderWorker(NoAlerts(), chain, interval_s=1).run_once()  # type: ignore[arg-type]
        self.assertEqual((mail.pending, len(self.sent)), (0, 1))


class FakeSmtp(threading.Thread):
    """Servidor SMTP mínimo (sin cifrado) para probar smtplib de punta a punta."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port: int = self.sock.getsockname()[1]
        self.messages: list[bytes] = []

    def run(self) -> None:
        conn, _ = self.sock.accept()
        with conn, conn.makefile("rwb") as f:
            def say(line: str) -> None:
                f.write(line.encode() + b"\r\n"); f.flush()
            say("220 fake ESMTP")
            data = False
            buf: list[bytes] = []
            while (raw := f.readline()):
                line = raw.rstrip(b"\r\n")
                if data:
                    if line == b".":
                        self.messages.append(b"\r\n".join(buf)); data = False; say("250 queued")
                    else:
                        buf.append(line[1:] if line.startswith(b"..") else line)
                    continue
                cmd = line.upper()
                if cmd.startswith(b"EHLO") or cmd.startswith(b"HELO"):
                    say("250 fake")
                elif cmd.startswith(b"DATA"):
                    data = True; buf = []; say("354 go")
                elif cmd.startswith(b"QUIT"):
                    say("221 bye"); break
                else:
                    say("250 ok")
        self.sock.close()


class SmtpIntegrationTests(unittest.TestCase):
    def test_real_smtplib_delivery(self) -> None:
        server = FakeSmtp()
        server.start()
        cfg = SmtpConfig.from_env({"SGADR_SMTP_HOST": "127.0.0.1", "SGADR_SMTP_PORT": str(server.port),
                                   "SGADR_SMTP_SECURITY": "none", "SGADR_SMTP_FROM": "sgadr@example.org"})
        assert cfg is not None
        EmailNotifier(cfg)(dict(ALERT))
        server.join(5)
        self.assertEqual(len(server.messages), 1)
        parsed = message_from_bytes(server.messages[0])
        self.assertEqual(parsed["To"], "centrodemonitoreochaco@gmail.com")
        self.assertIn("Fontana", parsed["Subject"])


if __name__ == "__main__":
    unittest.main()
