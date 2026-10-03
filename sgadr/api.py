"""API REST JSON sobre WSGI (solo biblioteca estándar).

El objeto `Api` es una aplicación WSGI estándar: corre con el servidor integrado
(`server.py`) o bajo cualquier servidor WSGI detrás de un proxy inverso con TLS.

Autenticación: cabecera `Authorization: Bearer <token>` (sin cookies, por lo que
no hay superficie CSRF). Toda respuesta es JSON y lleva cabeceras de seguridad.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final, TypeVar
from urllib.parse import parse_qs

from .alerts import AlertService
from .auth import AuthService
from .catalog import AREAS, MUNICIPALITIES, RESOURCE_TYPES
from .domain import (
    REPORT_INTERVAL,
    TRANSITIONS,
    Actor,
    AlertLevel,
    AlertSource,
    AuthenticationError,
    ConcurrencyConflict,
    DemandState,
    DomainError,
    DuplicateError,
    InvalidTransition,
    NewAlert,
    NewDemand,
    NotFound,
    PasswordChangeRequired,
    PermissionDenied,
    Role,
    ValidationError,
    VerificationSource,
)
from .service import DemandService
from .static import StaticFiles

log = logging.getLogger("sgadr.api")

Environ = dict[str, Any]
StartResponse = Callable[..., Any]
E = TypeVar("E", bound=StrEnum)

MAX_BODY_BYTES: Final = 64 * 1024

# Excepción de dominio -> (HTTP status, código estable para el cliente).
_ERROR_MAP: Final[tuple[tuple[type[DomainError], int, str], ...]] = (
    (ValidationError, 422, "validation_error"),
    (AuthenticationError, 401, "unauthenticated"),
    (PasswordChangeRequired, 403, "password_change_required"),
    (PermissionDenied, 403, "permission_denied"),
    (NotFound, 404, "not_found"),
    (InvalidTransition, 409, "invalid_transition"),
    (ConcurrencyConflict, 409, "concurrency_conflict"),
    (DuplicateError, 409, "duplicate"),
)

_SECURITY_HEADERS: Final[tuple[tuple[str, str], ...]] = (
    ("Content-Type", "application/json; charset=utf-8"),
    ("Server", "sgadr"),  # evita que wsgiref anuncie la versión exacta de Python
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
)


class HttpError(Exception):
    """Error HTTP explícito del borde de la API (formato, tamaño, tipo de contenido)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True, slots=True)
class Request:
    environ: Environ
    params: dict[str, str]
    token: str | None
    actor: Actor | None

    def query(self) -> dict[str, list[str]]:
        return parse_qs(self.environ.get("QUERY_STRING", ""), max_num_fields=20)

    def json(self) -> dict[str, Any]:
        """Lee y valida el cuerpo: Content-Type, tamaño máximo, UTF-8 estricto y objeto JSON."""
        ctype = self.environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise HttpError(415, "unsupported_media_type", "Se requiere application/json.")
        try:
            length = int(self.environ.get("CONTENT_LENGTH") or "")
        except ValueError:
            raise HttpError(411, "length_required", "Content-Length requerido.") from None
        if length <= 0:
            raise HttpError(400, "bad_request", "Cuerpo vacío.")
        if length > MAX_BODY_BYTES:
            raise HttpError(413, "payload_too_large", "Cuerpo demasiado grande.")
        raw = self.environ["wsgi.input"].read(length)
        if len(raw) != length:
            raise HttpError(400, "bad_request", "Cuerpo incompleto.")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HttpError(400, "bad_request", "JSON inválido.") from None
        if not isinstance(data, dict):
            raise ValidationError("El cuerpo debe ser un objeto JSON.")
        return data


Handler = Callable[[Request], tuple[int, Any]]


@dataclass(frozen=True, slots=True)
class _Route:
    method: str
    pattern: re.Pattern[str]
    handler: Handler
    public: bool = False


def _expect_keys(
    body: dict[str, Any], required: AbstractSet[str], optional: AbstractSet[str] = frozenset()
) -> None:
    """Esquema estricto: rechaza claves faltantes y desconocidas (mass-assignment)."""
    missing, unknown = required - body.keys(), body.keys() - required - optional
    if missing:
        raise ValidationError(f"Faltan campos: {', '.join(sorted(missing))}.")
    if unknown:
        raise ValidationError(f"Campos no permitidos: {', '.join(sorted(unknown))}.")


def _version(body: dict[str, Any]) -> int:
    """Versión esperada para el bloqueo optimista (entero positivo, sin bool ni float)."""
    version = body["expected_version"]
    if type(version) is not int or version < 1:
        raise ValidationError("'expected_version' debe ser un entero positivo.")
    return version


def _enum(kind: type[E], field: str, value: object) -> E:
    try:
        return kind(value if isinstance(value, str) else "")
    except ValueError:
        valid = ", ".join(m.value for m in kind)
        raise ValidationError(f"'{field}' inválido. Valores admitidos: {valid}.") from None


class Api:
    def __init__(
        self,
        demands: DemandService,
        auth: AuthService,
        alerts: AlertService,
        *,
        hsts: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        static_root: Path | None = None,
    ) -> None:
        self._demands = demands
        self._auth = auth
        self._alerts = alerts
        self._hsts = hsts
        self._clock = clock
        self._static = StaticFiles(static_root or Path(__file__).parent / "web")
        r = re.compile
        alert = r"^/api/v1/alerts/(?P<id>[0-9]{1,18})"
        self._pre_change_handlers = (self._me, self._logout, self._change_password)
        self._routes: tuple[_Route, ...] = (
            _Route("GET", r(r"^/healthz$"), self._health, public=True),
            _Route("POST", r(r"^/api/v1/login$"), self._login, public=True),
            _Route("POST", r(r"^/api/v1/logout$"), self._logout),
            _Route("GET", r(r"^/api/v1/me$"), self._me),
            _Route("GET", r(r"^/api/v1/meta$"), self._meta),
            _Route("POST", r(r"^/api/v1/password$"), self._change_password),
            _Route("GET", r(r"^/api/v1/users$"), self._user_list),
            _Route("POST", r(r"^/api/v1/users$"), self._user_create),
            _Route("POST", r(r"^/api/v1/users/(?P<username>[a-z0-9._-]{3,32})/active$"), self._user_active),
            _Route("POST", r(r"^/api/v1/users/(?P<username>[a-z0-9._-]{3,32})/password$"), self._user_password),
            _Route("GET", r(r"^/api/v1/demands$"), self._list),
            _Route("POST", r(r"^/api/v1/demands$"), self._register),
            _Route("GET", r(r"^/api/v1/demands/(?P<id>[0-9]{1,18})$"), self._get),
            _Route("POST", r(r"^/api/v1/demands/(?P<id>[0-9]{1,18})/transition$"), self._transition),
            _Route("GET", r(r"^/api/v1/audit/verify$"), self._verify_audit),
            _Route("GET", r(r"^/api/v1/audit$"), self._audit_list),
            _Route("GET", r(r"^/api/v1/alerts$"), self._alert_list),
            _Route("POST", r(r"^/api/v1/alerts$"), self._alert_register),
            _Route("GET", r(alert + r"$"), self._alert_get),
            _Route("POST", r(alert + r"/verify$"), self._alert_verify),
            _Route("POST", r(alert + r"/center-informed$"), self._alert_center_informed),
            _Route("POST", r(alert + r"/reports$"), self._alert_report),
            _Route("POST", r(alert + r"/level$"), self._alert_level),
        )

    # ---------- WSGI ----------

    def __call__(self, environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        if self._static.handles(environ.get("PATH_INFO", "")):
            return self._static.serve(environ, start_response, hsts=self._hsts)
        status, payload = self._dispatch(environ)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = [*_SECURITY_HEADERS, ("Content-Length", str(len(body)))]
        if self._hsts:
            headers.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
        if status == 401:
            headers.append(("WWW-Authenticate", "Bearer"))
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def _dispatch(self, environ: Environ) -> tuple[int, Any]:
        method, path = environ.get("REQUEST_METHOD", ""), environ.get("PATH_INFO", "")
        try:
            matched = [(rt, m) for rt in self._routes if (m := rt.pattern.fullmatch(path))]
            if not matched:
                raise HttpError(404, "not_found", "Recurso inexistente.")
            hit = next(((rt, m) for rt, m in matched if rt.method == method), None)
            if hit is None:
                raise HttpError(405, "method_not_allowed", "Método no permitido.")
            route, match = hit
            token = self._bearer(environ)
            actor: Actor | None = None
            if not route.public:
                if token is None:
                    raise AuthenticationError("Se requiere autenticación.")
                actor = self._auth.authenticate(token)
                # Clave temporal: hasta cambiarla solo puede ver su sesión, cambiarla o salir.
                if actor.must_change_password and route.handler not in self._pre_change_handlers:
                    raise PasswordChangeRequired("Debe cambiar su contraseña temporal antes de continuar.")
            status, payload = route.handler(Request(environ, match.groupdict(), token, actor))
            return status, payload
        except HttpError as exc:
            return exc.status, {"error": {"code": exc.code, "message": exc.message}}
        except DomainError as exc:
            for kind, status, code in _ERROR_MAP:
                if isinstance(exc, kind):
                    return status, {"error": {"code": code, "message": str(exc)}}
            return 400, {"error": {"code": "domain_error", "message": str(exc)}}
        except Exception:  # noqa: BLE001 - frontera del sistema: nunca filtrar detalles internos
            log.exception("Error no controlado en %s %s", method, path)
            return 500, {"error": {"code": "internal_error", "message": "Error interno."}}

    @staticmethod
    def _bearer(environ: Environ) -> str | None:
        scheme, _, token = environ.get("HTTP_AUTHORIZATION", "").partition(" ")
        token = token.strip()
        return token if scheme.lower() == "bearer" and token else None

    # ---------- handlers ----------

    @staticmethod
    def _health(_: Request) -> tuple[int, Any]:
        return 200, {"status": "ok"}

    def _login(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"username", "password"})
        session = self._auth.login(body["username"], body["password"])
        return 200, {
            "token": session.token,
            "expires_at": session.expires_at.isoformat(),
            "username": session.actor.username,
            "role": session.actor.role.value,
            "must_change_password": session.actor.must_change_password,
        }

    def _logout(self, req: Request) -> tuple[int, Any]:
        assert req.token is not None
        self._auth.logout(req.token)
        return 200, {"status": "ok"}

    def _me(self, req: Request) -> tuple[int, Any]:
        a = _need(req)
        # server_time permite a la interfaz calcular los relojes sin depender de la hora de la PC.
        return 200, {"username": a.username, "role": a.role.value, "area": a.area,
                     "must_change_password": a.must_change_password,
                     "server_time": self._clock().isoformat()}

    def _list(self, req: Request) -> tuple[int, Any]:
        only_open = req.query().get("all", ["0"])[0] != "1"
        return 200, {"items": self._demands.list_demands(_need(req), only_open=only_open)}

    def _register(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {
            "municipality", "locality", "resource_type",
            "quantity", "reason", "contact_name", "contact_phone",
        }, {"alert_level"})
        cmd = NewDemand(
            # Si se omite, se toma de la alerta activa del municipio.
            alert_level=_enum(AlertLevel, "alert_level", body["alert_level"])
            if "alert_level" in body else None,
            municipality=body["municipality"],
            locality=body["locality"],
            resource_type=body["resource_type"],
            quantity=body["quantity"],
            reason=body["reason"],
            contact_name=body["contact_name"],
            contact_phone=body["contact_phone"],
        )
        return 201, self._demands.register(_need(req), cmd)

    def _get(self, req: Request) -> tuple[int, Any]:
        return 200, self._demands.get(_need(req), int(req.params["id"]))

    def _transition(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"target", "expected_version"},
                     {"note", "assigned_area", "response_detail"})
        view = self._demands.transition(
            _need(req),
            int(req.params["id"]),
            _enum(DemandState, "target", body["target"]),
            expected_version=_version(body),
            note=body.get("note"),
            assigned_area=body.get("assigned_area"),
            response_detail=body.get("response_detail"),
        )
        return 200, view

    # ---------- alertas ----------

    def _alert_list(self, req: Request) -> tuple[int, Any]:
        query = req.query()
        items = self._alerts.list_alerts(
            _need(req),
            only_open=query.get("all", ["0"])[0] != "1",
            only_overdue=query.get("overdue", ["0"])[0] == "1",
        )
        return 200, {"items": items}

    def _alert_register(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"level", "source", "municipality", "summary"},
                     {"contact_name", "contact_phone"})
        cmd = NewAlert(
            level=_enum(AlertLevel, "level", body["level"]),
            source=_enum(AlertSource, "source", body["source"]),
            municipality=body["municipality"],
            summary=body["summary"],
            contact_name=body.get("contact_name"),
            contact_phone=body.get("contact_phone"),
        )
        return 201, self._alerts.register(_need(req), cmd)

    def _alert_get(self, req: Request) -> tuple[int, Any]:
        return 200, self._alerts.get(_need(req), int(req.params["id"]))

    def _alert_verify(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"source", "confirmed", "expected_version"}, {"note"})
        return 200, self._alerts.verify(
            _need(req), int(req.params["id"]),
            _enum(VerificationSource, "source", body["source"]), body["confirmed"],
            expected_version=_version(body), note=body.get("note"),
        )

    def _alert_center_informed(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"expected_version"})
        return 200, self._alerts.mark_center_informed(
            _need(req), int(req.params["id"]), expected_version=_version(body)
        )

    def _alert_report(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"municipal_status", "alert_lowered", "expected_version"})
        return 200, self._alerts.add_report(
            _need(req), int(req.params["id"]), body["municipal_status"], body["alert_lowered"],
            expected_version=_version(body),
        )

    def _alert_level(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"level", "note", "expected_version"})
        return 200, self._alerts.change_level(
            _need(req), int(req.params["id"]), _enum(AlertLevel, "level", body["level"]),
            body["note"], expected_version=_version(body),
        )

    def _meta(self, req: Request) -> tuple[int, Any]:
        """Reglas y catálogos que la interfaz necesita (única fuente de verdad: el servidor)."""
        _need(req)
        return 200, {
            "server_time": self._clock().isoformat(),
            "report_interval_hours": {
                level.value: int(delta.total_seconds() // 3600) for level, delta in REPORT_INTERVAL.items()
            },
            "demand_transitions": [
                {"from": src.value, "to": dst.value, "roles": sorted(r.value for r in roles)}
                for (src, dst), roles in TRANSITIONS.items()
            ],
            "areas": list(AREAS),
            "roles": [r.value for r in Role],
            "resources": [{"name": t.name, "suggested_area": t.suggested_area} for t in RESOURCE_TYPES],
            "municipalities": list(MUNICIPALITIES),
        }

    # ---------- cuentas ----------

    def _change_password(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"current_password", "new_password"})
        assert req.token is not None
        self._auth.change_password(_need(req), req.token, body["current_password"], body["new_password"])
        return 200, {"status": "ok"}

    def _user_list(self, req: Request) -> tuple[int, Any]:
        return 200, {"items": self._auth.list_users(_need(req))}

    def _user_create(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"username", "temporary_password", "role"}, {"area"})
        self._auth.admin_create_user(
            _need(req), body["username"], body["temporary_password"],
            _enum(Role, "role", body["role"]), body.get("area"),
        )
        return 201, {"status": "ok"}

    def _user_active(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"active"})
        if type(body["active"]) is not bool:
            raise ValidationError("'active' debe ser verdadero o falso.")
        self._auth.admin_set_active(_need(req), req.params["username"], body["active"])
        return 200, {"status": "ok"}

    def _user_password(self, req: Request) -> tuple[int, Any]:
        body = req.json()
        _expect_keys(body, {"temporary_password"})
        self._auth.admin_reset_password(_need(req), req.params["username"], body["temporary_password"])
        return 200, {"status": "ok"}

    def _audit_list(self, req: Request) -> tuple[int, Any]:
        if _need(req).role not in (Role.MONITOREO, Role.COMITE):
            raise PermissionDenied("Solo Monitoreo y Comité pueden consultar la bitácora.")
        try:
            limit = int(req.query().get("limit", ["100"])[0])
        except ValueError:
            raise ValidationError("'limit' debe ser un entero.") from None
        return 200, {"items": self._demands.audit_recent(max(1, min(limit, 500)))}

    def _verify_audit(self, req: Request) -> tuple[int, Any]:
        if _need(req).role not in (Role.MONITOREO, Role.COMITE):
            raise PermissionDenied("Solo Monitoreo y Comité pueden verificar la bitácora.")
        return 200, {"valid": self._demands.verify_audit()}


def _need(req: Request) -> Actor:
    """Actor autenticado de la request (las rutas no públicas siempre lo tienen)."""
    if req.actor is None:
        raise AuthenticationError("Se requiere autenticación.")
    return req.actor
