"""Utilidades compartidas por las pruebas: reloj controlable, usuarios y cliente WSGI en memoria."""

from __future__ import annotations

import io
import json
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import mock
from wsgiref.util import setup_testing_defaults

from sgadr import security
from sgadr.alerts import AlertService
from sgadr.api import Api
from sgadr.auth import AuthService
from sgadr.domain import Role
from sgadr.service import DemandService
from sgadr.store import Store

PASSWORD = "clave-segura-123"
_patcher: mock._patch[int] | None = None


def setUpModule() -> None:
    """Reduce el costo de scrypt SOLO en las pruebas para que la suite sea rápida.

    Cada módulo de prueba lo importa con `from .support import setUpModule, tearDownModule`.
    """
    global _patcher
    _patcher = mock.patch.object(security, "_N", 2**10)
    _patcher.start()


def tearDownModule() -> None:
    if _patcher is not None:
        _patcher.stop()


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


DEMAND = {
    "alert_level": "naranja", "municipality": "Resistencia", "locality": "Barrio Norte",
    "resource_type": "Colchones", "quantity": 50,
    "reason": "Anegamiento con familias evacuadas.",
    "contact_name": "Intendente X", "contact_phone": "+54 362 4000000",
}

ALERT_APA = {
    "level": "amarillo", "source": "apa", "municipality": "Resistencia",
    "summary": "Pronóstico de lluvia significativa en 48-72 hs.",
}
ALERT_MUNI = {
    "level": "naranja", "source": "municipio", "municipality": "Barranqueras",
    "summary": "Crecida del río con áreas anegadas.",
    "contact_name": "Intendente Y", "contact_phone": "+54 362 4111111",
}

USERS: tuple[tuple[str, Role, str | None], ...] = (
    ("op07", Role.NODO_07, None), ("op00", Role.NODO_00, None),
    ("comite", Role.COMITE, None), ("salud", Role.AREA, "Salud"),
    ("mon", Role.MONITOREO, None), ("admin", Role.ADMIN, None),
)


class ApiTestCase(unittest.TestCase):
    """Base: aplicación completa en memoria, reloj falso y un usuario por rol."""

    def setUp(self) -> None:
        self.clock = FakeClock()
        self.store = Store(":memory:")
        self.auth = AuthService(self.store, self.clock, max_attempts=3)
        self.demands = DemandService(self.store, self.clock)
        self.alerts = AlertService(self.store, self.clock)
        self.api = Api(self.demands, self.auth, self.alerts)
        for name, role, area in USERS:
            self.auth.create_user(name, PASSWORD, role, area)

    def tearDown(self) -> None:
        self.store.close()

    def call(
        self, method: str, path: str, body: Any = None, token: str | None = None,
        *, ctype: str = "application/json", raw: bytes | None = None, length: int | None = None,
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        route, _, query = path.partition("?")
        environ: dict[str, Any] = {}
        setup_testing_defaults(environ)
        environ.update({
            "REQUEST_METHOD": method, "PATH_INFO": route, "QUERY_STRING": query,
            "CONTENT_TYPE": ctype if payload else "",
            "CONTENT_LENGTH": str(len(payload) if length is None else length) if payload else "",
            "wsgi.input": io.BytesIO(payload),
        })
        if token:
            environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        seen: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            seen["status"], seen["headers"] = int(status.split()[0]), dict(headers)

        data = b"".join(self.api(environ, start_response))
        return seen["status"], seen["headers"], json.loads(data)

    def login(self, user: str, password: str = PASSWORD) -> str:
        status, _, body = self.call("POST", "/api/v1/login", {"username": user, "password": password})
        self.assertEqual(status, 200, body)
        return str(body["token"])

    def step(self, token: str, did: int, target: str, version: int, **extra: Any) -> dict[str, Any]:
        status, _, body = self.call(
            "POST", f"/api/v1/demands/{did}/transition",
            {"target": target, "expected_version": version, **extra}, token,
        )
        self.assertEqual(status, 200, body)
        return body
