"""Aviso por correo de reportes de estado vencidos (SMTP con la biblioteca estándar).

Decisiones de seguridad y operación:
- La configuración sale de variables de entorno (la clave nunca viaja por argumentos de
  línea de comandos, donde cualquier usuario del servidor la vería con `ps`).
- STARTTLS o SSL con verificación de certificado; sin cifrado solo se admite sin credenciales.
- El correo no lleva datos de contacto del municipio (compartimentación 07/00: el correo
  no es un canal controlado). Solo código, municipio, nivel y atraso.
- Si el envío falla, el aviso queda en una cola en memoria y se reintenta en cada ciclo del
  worker; además se deja un ERROR en el log. Un reinicio del servicio descarta esa cola.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Final, Literal

log = logging.getLogger("sgadr.mailer")

DEFAULT_RECIPIENT: Final = "centrodemonitoreochaco@gmail.com"
Security = Literal["starttls", "ssl", "none"]
_SECURITY: Final = ("starttls", "ssl", "none")
_DEFAULT_PORT: Final[dict[str, int]] = {"starttls": 587, "ssl": 465, "none": 25}
_ADDRESS: Final = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")

Transport = Callable[[EmailMessage], None]


class MailConfigError(ValueError):
    """Configuración SMTP inválida o incompleta."""


def _address(value: str, what: str) -> str:
    addr = parseaddr(value)[1]
    if not _ADDRESS.fullmatch(addr):
        raise MailConfigError(f"Dirección inválida en {what}.")
    return addr


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    sender: str
    recipients: tuple[str, ...]
    security: Security = "starttls"
    username: str | None = None
    password: str | None = None
    timeout: float = 15.0

    def __repr__(self) -> str:  # la clave no debe aparecer en logs ni trazas
        return (f"SmtpConfig(host={self.host!r}, port={self.port}, sender={self.sender!r}, "
                f"recipients={self.recipients!r}, security={self.security!r}, "
                f"username={self.username!r}, password={'***' if self.password else None})")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> SmtpConfig | None:
        """Devuelve None si el correo no está configurado (no hay SGADR_SMTP_HOST)."""
        host = env.get("SGADR_SMTP_HOST", "").strip()
        if not host:
            return None
        security = env.get("SGADR_SMTP_SECURITY", "starttls").strip().lower()
        if security not in _SECURITY:
            raise MailConfigError(f"SGADR_SMTP_SECURITY debe ser uno de: {', '.join(_SECURITY)}.")
        try:
            port = int(env.get("SGADR_SMTP_PORT", "") or _DEFAULT_PORT[security])
        except ValueError:
            raise MailConfigError("SGADR_SMTP_PORT debe ser un entero.") from None
        if not 0 < port < 65536:
            raise MailConfigError("SGADR_SMTP_PORT fuera de rango.")
        username = env.get("SGADR_SMTP_USER", "").strip() or None
        password = env.get("SGADR_SMTP_PASSWORD") or None
        if bool(username) != bool(password):
            raise MailConfigError("SGADR_SMTP_USER y SGADR_SMTP_PASSWORD deben indicarse juntos.")
        if username and security == "none":
            raise MailConfigError("No se envían credenciales SMTP sin cifrado (use starttls o ssl).")
        sender = _address(env.get("SGADR_SMTP_FROM", "") or (username or ""), "SGADR_SMTP_FROM")
        raw_to = env.get("SGADR_SMTP_TO", "") or DEFAULT_RECIPIENT
        recipients = tuple(_address(p, "SGADR_SMTP_TO") for p in raw_to.split(",") if p.strip())
        if not recipients:
            raise MailConfigError("SGADR_SMTP_TO no tiene destinatarios.")
        return cls(host, port, sender, recipients, security, username, password)  # type: ignore[arg-type]  # security validada arriba


def build_message(config: SmtpConfig, alert: Mapping[str, Any]) -> EmailMessage:
    """Arma el correo de un reporte vencido (función pura, sin red)."""
    clean = lambda v: _CONTROL.sub(" ", str(v)).strip()  # noqa: E731 - evita inyección de cabeceras
    code, muni, level = clean(alert["code"]), clean(alert["municipality"]), clean(alert["level"])
    minutes = int(alert.get("overdue_minutes", 0))
    hours, rest = divmod(minutes, 60)
    late = f"{hours} h {rest} min" if hours else f"{rest} min"
    msg = EmailMessage()
    msg["Subject"] = f"[SGADR] Reporte vencido: {muni} (alerta {level})"
    msg["From"] = config.sender
    msg["To"] = ", ".join(config.recipients)
    msg.set_content(
        "Reporte de estado vencido\n\n"
        f"Alerta: {code}\nMunicipio: {muni}\nNivel: {level}\nAtraso: {late}\n\n"
        "Acción: el Nodo 07 debe solicitar el reporte de estado al municipio.\n\n"
        "Aviso automático del Sistema de Gestión de Alertas y Demandas. "
        "No incluye datos de contacto; consulte el sistema.\n"
    )
    return msg


class EmailNotifier:
    """Notificador compatible con ReminderWorker: se invoca con el detalle de la alerta."""

    def __init__(self, config: SmtpConfig, *, transport: Transport | None = None, max_pending: int = 100) -> None:
        self._config = config
        self._transport = transport or self._smtp_send
        self._pending: deque[EmailMessage] = deque(maxlen=max_pending)

    @property
    def pending(self) -> int:
        return len(self._pending)

    def __call__(self, alert: Mapping[str, Any]) -> None:
        message = build_message(self._config, alert)
        if not self._try(message):
            self._pending.append(message)

    def flush(self) -> int:
        """Reintenta los pendientes en orden; se detiene en el primer fallo. Devuelve los enviados."""
        sent = 0
        while self._pending:
            if not self._try(self._pending[0]):
                break
            self._pending.popleft()
            sent += 1
        return sent

    def _try(self, message: EmailMessage) -> bool:
        try:
            self._transport(message)
        except (OSError, smtplib.SMTPException) as exc:
            log.error("No se pudo enviar '%s' (%s); se reintentará.", message["Subject"], type(exc).__name__)
            return False
        log.info("Correo enviado: %s", message["Subject"])
        return True

    def _smtp_send(self, message: EmailMessage) -> None:
        cfg = self._config
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout, context=context)
        else:
            client = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
        with client:
            if cfg.security == "starttls":
                client.starttls(context=context)
            if cfg.username and cfg.password:
                client.login(cfg.username, cfg.password)
            client.send_message(message)

    def send_test(self) -> None:
        """Envío de prueba (comando `test-mail`): propaga el error para diagnosticar."""
        self._transport(build_message(self._config, {
            "code": "PRUEBA", "municipality": "Mensaje de prueba", "level": "amarillo", "overdue_minutes": 0,
        }))
