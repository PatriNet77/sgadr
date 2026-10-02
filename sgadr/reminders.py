"""Recordatorios de reportes de estado vencidos (ciclos de 12 h y 6 h).

El worker consulta periódicamente `AlertService.flag_overdue()`: cada vencimiento se
notifica UNA sola vez y queda en la bitácora. El canal de notificación es un callable
inyectable (`Notifier`): por defecto escribe un WARNING en el log; más adelante puede
enviar SMS, WhatsApp o correo sin modificar el núcleo (ver mailer.EmailNotifier).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .alerts import AlertService

log = logging.getLogger("sgadr.reminders")

Notifier = Callable[[dict[str, Any]], None]


class ChainedNotifier:
    """Varios canales en cadena: uno que falla no impide que los demás reciban el aviso."""

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    def __call__(self, alert: dict[str, Any]) -> None:
        for notifier in self._notifiers:
            try:
                notifier(alert)
            except Exception:  # noqa: BLE001
                log.exception("Falló un canal de notificación para %s", alert.get("code"))

    def flush(self) -> None:
        for notifier in self._notifiers:
            flush = getattr(notifier, "flush", None)
            if callable(flush):
                flush()


def log_notifier(alert: dict[str, Any]) -> None:
    """Notificador por defecto: deja constancia en el log del servidor."""
    log.warning(
        "REPORTE VENCIDO %s (%s, %s): solicitar estado al municipio. Vencido hace %d min.",
        alert["code"], alert["municipality"], alert["level"], alert["overdue_minutes"],
    )


class ReminderWorker:
    def __init__(
        self,
        alerts: AlertService,
        notifier: Notifier = log_notifier,
        *,
        interval_s: float = 60.0,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s debe ser positivo.")
        self._alerts = alerts
        self._notifier = notifier
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> int:
        """Procesa los vencimientos pendientes y devuelve cuántas alertas se notificaron."""
        overdue = self._alerts.flag_overdue()
        for alert in overdue:
            try:
                self._notifier(alert)
            except Exception:  # noqa: BLE001 - un canal caído no debe frenar a los demás
                log.exception("Falló la notificación de %s", alert.get("code"))
        flush = getattr(self._notifier, "flush", None)  # reintenta los envíos que habían fallado
        if callable(flush):
            try:
                flush()
            except Exception:  # noqa: BLE001
                log.exception("Falló el reintento de notificaciones pendientes")
        return len(overdue)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sgadr-reminders", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _loop(self) -> None:
        # Event.wait hace de temporizador y permite un cierre inmediato al llamar a stop().
        while not self._stop.wait(self._interval):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - el worker debe sobrevivir a errores transitorios
                log.exception("Error en el ciclo de recordatorios")
