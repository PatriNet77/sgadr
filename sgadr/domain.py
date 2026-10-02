"""Dominio SGADR: roles, estados, reglas de transición y visibilidad por rol.

Módulo puro (sin I/O ni dependencias): fuente única de verdad de las reglas del
circuito Alerta -> Demanda -> Autorización -> Respuesta -> Cierre.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import Final


class AlertLevel(StrEnum):
    AMARILLO = "amarillo"
    NARANJA = "naranja"
    ROJO = "rojo"


class Role(StrEnum):
    NODO_07 = "nodo_07"      # Información: único punto de ingreso de demandas
    NODO_00 = "nodo_00"      # Vinculación con recursos provinciales
    COMITE = "comite"        # Comité de Emergencia Provincial (autoriza)
    MONITOREO = "monitoreo"  # Centro de Monitoreo (solo lectura)
    AREA = "area"            # Área provincial que ejecuta la respuesta
    ADMIN = "admin"          # Administración del sistema: gestiona cuentas, no ve el contenido operativo


class DemandState(StrEnum):
    RECIBIDA = "recibida"
    VERIFICADA = "verificada"
    PENDIENTE_AUTORIZACION = "pendiente_autorizacion"
    AUTORIZADA = "autorizada"
    ASIGNADA = "asignada"
    EN_EJECUCION = "en_ejecucion"
    RESPONDIDA = "respondida"
    CERRADA = "cerrada"
    RECHAZADA = "rechazada"
    RECURSOS_AGOTADOS = "recursos_agotados"


class AlertState(StrEnum):
    PENDIENTE_VERIFICACION = "pendiente_verificacion"  # ingresó por un municipio
    ACTIVA = "activa"
    CERRADA = "cerrada"        # el municipio informó que la alerta bajó
    DESCARTADA = "descartada"  # una verificación (APA o policía) no la confirmó


class AlertSource(StrEnum):
    APA = "apa"                # camino principal de ingreso
    MUNICIPIO = "municipio"    # informa el intendente o el Comité de Emergencia Local


class VerificationSource(StrEnum):
    APA = "apa"
    POLICIA = "policia"


# Frecuencia con la que el Nodo 07 solicita el reporte de estado al municipio
# (circuitos 1 a 3 del documento: amarillo 12 h; naranja y rojo 6 h).
REPORT_INTERVAL: Final[dict[AlertLevel, timedelta]] = {
    AlertLevel.AMARILLO: timedelta(hours=12),
    AlertLevel.NARANJA: timedelta(hours=6),
    AlertLevel.ROJO: timedelta(hours=6),
}

# Separación de funciones: quien administra cuentas no lee ni modifica el contenido operativo.
DEMAND_READ_ROLES: Final[frozenset[Role]] = frozenset(set(Role) - {Role.ADMIN})

# Las áreas ejecutoras solo ven demandas asignadas; las alertas no forman parte de su circuito.
ALERT_READ_ROLES: Final[frozenset[Role]] = frozenset(
    {Role.NODO_07, Role.NODO_00, Role.COMITE, Role.MONITOREO}
)
# Compartimentación: el contacto del municipio no llega al Nodo 00 ni a Monitoreo.
ALERT_HIDDEN_FIELDS: Final[dict[Role, frozenset[str]]] = {
    Role.NODO_00: frozenset({"contact_name", "contact_phone"}),
    Role.MONITOREO: frozenset({"contact_name", "contact_phone"}),
}

TERMINAL_STATES: Final[frozenset[DemandState]] = frozenset(
    {DemandState.CERRADA, DemandState.RECHAZADA}
)

S = DemandState
# (estado actual, estado destino) -> roles autorizados a ejecutar la transición.
TRANSITIONS: Final[dict[tuple[DemandState, DemandState], frozenset[Role]]] = {
    (S.RECIBIDA, S.VERIFICADA): frozenset({Role.NODO_00}),
    (S.RECIBIDA, S.RECHAZADA): frozenset({Role.NODO_00}),
    (S.VERIFICADA, S.PENDIENTE_AUTORIZACION): frozenset({Role.NODO_00}),
    (S.PENDIENTE_AUTORIZACION, S.AUTORIZADA): frozenset({Role.COMITE}),
    (S.PENDIENTE_AUTORIZACION, S.RECHAZADA): frozenset({Role.COMITE}),
    (S.AUTORIZADA, S.ASIGNADA): frozenset({Role.NODO_00}),
    (S.ASIGNADA, S.EN_EJECUCION): frozenset({Role.AREA}),
    (S.ASIGNADA, S.RECURSOS_AGOTADOS): frozenset({Role.AREA}),
    (S.EN_EJECUCION, S.RESPONDIDA): frozenset({Role.AREA}),
    (S.EN_EJECUCION, S.RECURSOS_AGOTADOS): frozenset({Role.AREA}),
    (S.RECURSOS_AGOTADOS, S.ASIGNADA): frozenset({Role.NODO_00}),  # reasignar
    (S.RESPONDIDA, S.CERRADA): frozenset({Role.NODO_00}),
}

# Compartimentación 07/00 como control técnico: campos que cada rol NO recibe.
HIDDEN_FIELDS: Final[dict[Role, frozenset[str]]] = {
    Role.NODO_07: frozenset({"assigned_area"}),
    Role.NODO_00: frozenset({"contact_name", "contact_phone"}),
    Role.AREA: frozenset({"contact_name", "contact_phone"}),
    Role.MONITOREO: frozenset({"contact_name", "contact_phone"}),
}


class DomainError(Exception):
    """Base de los errores de negocio (mapeables a códigos HTTP 4xx)."""


class ValidationError(DomainError): ...
class PermissionDenied(DomainError): ...


class PasswordChangeRequired(PermissionDenied):
    """La cuenta usa una clave temporal: solo puede cambiarla antes de operar."""
class InvalidTransition(DomainError): ...
class ConcurrencyConflict(DomainError): ...
class NotFound(DomainError): ...
class AuthenticationError(DomainError): ...
class DuplicateError(DomainError): ...


@dataclass(frozen=True, slots=True)
class Actor:
    """Identidad ya autenticada que ejecuta una acción."""

    username: str
    role: Role
    area: str | None = None
    must_change_password: bool = False


_PHONE: Final = re.compile(r"^\+?[0-9][0-9 ()\-]{5,19}$")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(field: str, value: object, *, max_len: int, min_len: int = 1) -> str:
    """Normaliza y valida texto libre; rechaza tipos erróneos y caracteres de control."""
    if not isinstance(value, str):
        raise ValidationError(f"'{field}' debe ser texto.")
    text = value.strip()
    if not min_len <= len(text) <= max_len:
        raise ValidationError(f"'{field}' debe tener entre {min_len} y {max_len} caracteres.")
    if _CONTROL.search(text):
        raise ValidationError(f"'{field}' contiene caracteres no permitidos.")
    return text


def normalize_key(text: str) -> str:
    """Clave canónica de un nombre (sin tildes, minúsculas, espacios colapsados).

    Evita duplicados por variantes de escritura: 'Sáenz  Peña' == 'saenz pena'.
    """
    base = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


@dataclass(frozen=True, slots=True)
class NewAlert:
    """Datos de ingreso de una alerta (solo por el Nodo 07)."""

    level: AlertLevel
    source: AlertSource
    municipality: str
    summary: str
    contact_name: str | None = None
    contact_phone: str | None = None

    def validated(self) -> NewAlert:
        if not isinstance(self.level, AlertLevel):
            raise ValidationError("Nivel de alerta inválido.")
        if not isinstance(self.source, AlertSource):
            raise ValidationError("Origen de alerta inválido.")
        municipality = clean_text("municipality", self.municipality, max_len=80)
        summary = clean_text("summary", self.summary, max_len=2000, min_len=10)
        if self.source is AlertSource.APA:
            if self.contact_name is not None or self.contact_phone is not None:
                raise ValidationError("Una alerta de APA no lleva contacto municipal.")
            return replace(self, municipality=municipality, summary=summary)
        if self.contact_name is None or self.contact_phone is None:
            raise ValidationError("Una alerta municipal requiere nombre y teléfono de contacto.")
        phone = clean_text("contact_phone", self.contact_phone, max_len=20, min_len=6)
        if not _PHONE.fullmatch(phone):
            raise ValidationError("Teléfono de contacto con formato inválido.")
        return replace(
            self, municipality=municipality, summary=summary, contact_phone=phone,
            contact_name=clean_text("contact_name", self.contact_name, max_len=120),
        )


@dataclass(frozen=True, slots=True)
class NewDemand:
    """Datos de ingreso de una demanda (solo por el Nodo 07)."""

    alert_level: AlertLevel | None  # si es None se toma de la alerta vigente del municipio
    municipality: str
    locality: str
    resource_type: str
    quantity: int
    reason: str
    contact_name: str
    contact_phone: str

    def validated(self) -> NewDemand:
        if self.alert_level is not None and not isinstance(self.alert_level, AlertLevel):
            raise ValidationError("Nivel de alerta inválido.")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 1_000_000:
            raise ValidationError("'quantity' debe ser un entero entre 1 y 1.000.000.")
        phone = clean_text("contact_phone", self.contact_phone, max_len=20, min_len=6)
        if not _PHONE.fullmatch(phone):
            raise ValidationError("Teléfono de contacto con formato inválido.")
        return replace(
            self,
            municipality=clean_text("municipality", self.municipality, max_len=80),
            locality=clean_text("locality", self.locality, max_len=120),
            resource_type=clean_text("resource_type", self.resource_type, max_len=120),
            reason=clean_text("reason", self.reason, max_len=2000, min_len=10),
            contact_name=clean_text("contact_name", self.contact_name, max_len=120),
            contact_phone=phone,
        )
