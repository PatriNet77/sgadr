"""Pruebas del soporte web: archivos estáticos, /meta, bitácora y catálogos."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from wsgiref.util import setup_testing_defaults

from sgadr.api import Api
from sgadr.catalog import AREAS, RESOURCE_TYPES
from sgadr.domain import TRANSITIONS, Actor, Role, ValidationError

from .support import DEMAND, PASSWORD, ApiTestCase, setUpModule, tearDownModule  # noqa: F401


def fetch(api: Api, method: str, path: str, **headers: str) -> tuple[int, dict[str, str], bytes]:
    """Cliente WSGI crudo (la respuesta de los estáticos no es JSON)."""
    environ: dict[str, Any] = {}
    setup_testing_defaults(environ)
    environ.update({"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
                    "wsgi.input": io.BytesIO(b"")})
    environ.update({f"HTTP_{k.upper()}": v for k, v in headers.items()})
    seen: dict[str, Any] = {}

    def start_response(status: str, hdrs: list[tuple[str, str]]) -> None:
        seen["status"], seen["headers"] = int(status.split()[0]), dict(hdrs)

    body = b"".join(api(environ, start_response))
    return seen["status"], seen["headers"], body


class StaticFilesTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        root = base / "web"
        (root / "js").mkdir(parents=True)
        (root / "index.html").write_text("<!doctype html><title>SGADR</title>", encoding="utf-8")
        (root / "js" / "app.js").write_text("export const ok = true;", encoding="utf-8")
        (root / ".oculto.js").write_text("secreto", encoding="utf-8")
        (root / "tool.exe").write_bytes(b"MZ")
        (base / "fuera.js").write_text("fuera de la raíz", encoding="utf-8")
        try:
            (root / "js" / "enlace.js").symlink_to(base / "fuera.js")
        except OSError:
            pass  # plataformas sin symlinks
        self.web = Api(self.demands, self.auth, self.alerts, static_root=root)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def test_index_is_served_without_authentication_and_with_strict_csp(self) -> None:
        status, headers, body = fetch(self.web, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"SGADR", body)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        csp = headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Server"], "sgadr")

    def test_content_types_and_conditional_requests(self) -> None:
        status, headers, body = fetch(self.web, "GET", "/static/js/app.js")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        self.assertEqual(body, b"export const ok = true;")
        status, _, body = fetch(self.web, "GET", "/static/js/app.js", if_none_match=headers["ETag"])
        self.assertEqual((status, body), (304, b""))

    def test_head_has_no_body_and_other_methods_are_refused(self) -> None:
        status, _, body = fetch(self.web, "HEAD", "/")
        self.assertEqual((status, body), (200, b""))
        status, headers, _ = fetch(self.web, "POST", "/")
        self.assertEqual((status, headers["Allow"]), (405, "GET, HEAD"))

    def test_path_traversal_and_unsafe_targets_are_not_found(self) -> None:
        attacks = (
            "/static/../fuera.js", "/static/js/../../fuera.js", "/static/..", "/static/js/..%2f..%2ffuera.js",
            "/static//etc/passwd", "/static/.oculto.js", "/static/js", "/static/", "/static/tool.exe",
            "/static/js\\app.js", "/static/js/app.js\x00.png", "/static/js/enlace.js", "/static/nada.js",
        )
        for path in attacks:
            status, _, body = fetch(self.web, "GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"fuera de la ra", body, path)
            self.assertNotIn(b"secreto", body, path)

    def test_api_routes_are_not_shadowed_by_static_serving(self) -> None:
        self.assertEqual(self.call("GET", "/api/v1/me")[0], 401)
        self.assertEqual(fetch(self.web, "GET", "/api/v1/me")[0], 401)


class MetaTests(ApiTestCase):
    def test_meta_requires_authentication(self) -> None:
        self.assertEqual(self.call("GET", "/api/v1/meta")[0], 401)

    def test_meta_publishes_rules_and_catalogs(self) -> None:
        status, _, meta = self.call("GET", "/api/v1/meta", token=self.login("op00"))
        self.assertEqual(status, 200)
        self.assertEqual(meta["report_interval_hours"], {"amarillo": 12, "naranja": 6, "rojo": 6})
        self.assertEqual(len(meta["demand_transitions"]), len(TRANSITIONS))
        self.assertIn({"from": "recibida", "to": "verificada", "roles": ["nodo_00"]}, meta["demand_transitions"])
        self.assertIn({"from": "pendiente_autorizacion", "to": "autorizada", "roles": ["comite"]},
                      meta["demand_transitions"])
        self.assertEqual(meta["areas"], list(AREAS))
        self.assertEqual(len(meta["resources"]), len(RESOURCE_TYPES))
        self.assertIn("Resistencia", meta["municipalities"])

    def test_meta_server_time_uses_the_injected_clock(self) -> None:
        api = Api(self.demands, self.auth, self.alerts, clock=self.clock)
        token = self.login("op07")
        original, self.api = self.api, api
        try:
            meta = self.call("GET", "/api/v1/meta", token=token)[2]
        finally:
            self.api = original
        self.assertEqual(meta["server_time"], self.clock.now.isoformat())


class AuditListTests(ApiTestCase):
    def test_only_monitoreo_and_comite_can_read_the_audit_trail(self) -> None:
        for user in ("op07", "op00", "salud"):
            self.assertEqual(self.call("GET", "/api/v1/audit", token=self.login(user))[0], 403, user)
        for user in ("mon", "comite"):
            self.assertEqual(self.call("GET", "/api/v1/audit", token=self.login(user))[0], 200, user)

    def test_entries_are_newest_first_and_limit_is_clamped(self) -> None:
        t07, tmon = self.login("op07"), self.login("mon")
        self.call("POST", "/api/v1/demands", DEMAND, t07)
        items = self.call("GET", "/api/v1/audit?limit=3", token=tmon)[2]["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual([i["seq"] for i in items], sorted((i["seq"] for i in items), reverse=True))
        self.assertEqual(items[0]["entry"]["action"], "register")
        self.assertEqual(len(items[0]["hash"]), 12)
        self.assertEqual(len(self.call("GET", "/api/v1/audit?limit=0", token=tmon)[2]["items"]), 1)
        self.assertEqual(self.call("GET", "/api/v1/audit?limit=abc", token=tmon)[0], 422)
        json.dumps(items)  # serializable


class AreaCatalogTests(ApiTestCase):
    def test_assignment_requires_a_known_area(self) -> None:
        t07, t00, tcom = self.login("op07"), self.login("op00"), self.login("comite")
        did = self.call("POST", "/api/v1/demands", DEMAND, t07)[2]["id"]
        self.step(t00, did, "verificada", 1)
        self.step(t00, did, "pendiente_autorizacion", 2)
        self.step(tcom, did, "autorizada", 3)
        status, _, body = self.call("POST", f"/api/v1/demands/{did}/transition",
                                    {"target": "asignada", "expected_version": 4,
                                     "assigned_area": "Ministerio Inventado"}, t00)
        self.assertEqual((status, body["error"]["code"]), (422, "validation_error"))
        self.step(t00, did, "asignada", 4, assigned_area="Vialidad Provincial")

    def test_area_users_must_belong_to_a_known_area(self) -> None:
        with self.assertRaises(ValidationError):
            self.auth.create_user("otra", PASSWORD, Role.AREA, "Ministerio Inventado")
        self.auth.create_user("vial", PASSWORD, Role.AREA, "Vialidad Provincial")
        self.assertIsInstance(Actor("vial", Role.AREA, "Vialidad Provincial"), Actor)

    def test_every_suggested_area_is_a_valid_area(self) -> None:
        for resource in RESOURCE_TYPES:
            self.assertTrue(resource.suggested_area is None or resource.suggested_area in AREAS, resource)


if __name__ == "__main__":
    unittest.main()
