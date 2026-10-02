"""Pruebas de la capa de autenticación y de la API HTTP (cliente WSGI en memoria)."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta
from unittest import mock

from sgadr.api import MAX_BODY_BYTES

from .support import DEMAND, PASSWORD, ApiTestCase, setUpModule, tearDownModule  # noqa: F401


class AuthTests(ApiTestCase):
    def test_health_is_public(self) -> None:
        status, _, body = self.call("GET", "/healthz")
        self.assertEqual((status, body["status"]), (200, "ok"))

    def test_login_and_me(self) -> None:
        token = self.login("salud")
        status, _, body = self.call("GET", "/api/v1/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual((body["role"], body["area"]), ("area", "Salud"))

    def test_failures_are_indistinguishable(self) -> None:
        a = self.call("POST", "/api/v1/login", {"username": "op07", "password": "incorrecta-123"})
        b = self.call("POST", "/api/v1/login", {"username": "fantasma", "password": "incorrecta-123"})
        self.assertEqual((a[0], b[0]), (401, 401))
        self.assertEqual(a[2], b[2])

    def test_lockout_and_automatic_release(self) -> None:
        for _ in range(3):
            self.call("POST", "/api/v1/login", {"username": "op07", "password": "mala-clave-123"})
        status, _, _ = self.call("POST", "/api/v1/login", {"username": "op07", "password": PASSWORD})
        self.assertEqual(status, 401)  # bloqueado aun con la clave correcta
        self.clock.advance(timedelta(minutes=6))
        self.login("op07")

    def test_protected_routes_require_token(self) -> None:
        status, headers, _ = self.call("GET", "/api/v1/demands")
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"], "Bearer")
        self.assertEqual(self.call("GET", "/api/v1/me", token="token-inventado")[0], 401)

    def test_logout_revokes_token(self) -> None:
        token = self.login("op07")
        self.assertEqual(self.call("POST", "/api/v1/logout", token=token)[0], 200)
        self.assertEqual(self.call("GET", "/api/v1/me", token=token)[0], 401)

    def test_session_expires(self) -> None:
        token = self.login("op07")
        self.clock.advance(timedelta(hours=9))
        self.assertEqual(self.call("GET", "/api/v1/me", token=token)[0], 401)

    def test_deactivated_user_loses_access(self) -> None:
        token = self.login("op07")
        self.auth.deactivate_user("op07")
        self.assertEqual(self.call("GET", "/api/v1/me", token=token)[0], 401)
        status, _, _ = self.call("POST", "/api/v1/login", {"username": "op07", "password": PASSWORD})
        self.assertEqual(status, 401)

    def test_only_hash_of_token_is_stored(self) -> None:
        token = self.login("op07")
        stored = [r["token_hash"] for r in self.store.read("SELECT token_hash FROM sessions")]
        self.assertNotIn(token, stored)


class CircuitOverHttpTests(ApiTestCase):
    def test_full_circuit_with_role_projection(self) -> None:
        t07, t00, tcom, tsal, tmon = (self.login(u) for u in ("op07", "op00", "comite", "salud", "mon"))

        status, _, created = self.call("POST", "/api/v1/demands", DEMAND, t07)
        self.assertEqual(status, 201, created)
        did, code = created["id"], created["code"]
        self.assertEqual((created["state"], created["version"]), ("recibida", 1))
        self.assertIn("contact_phone", created)          # el Nodo 07 ve al municipio
        self.assertNotIn("assigned_area", created)       # ...pero no a las áreas

        v = self.step(t00, did, "verificada", 1)
        self.assertNotIn("contact_phone", v)             # el Nodo 00 no ve al municipio
        self.step(t00, did, "pendiente_autorizacion", 2)
        self.step(tcom, did, "autorizada", 3)
        self.step(t00, did, "asignada", 4, assigned_area="Salud")
        self.step(tsal, did, "en_ejecucion", 5)
        self.step(tsal, did, "respondida", 6, response_detail="Entregados 50 colchones, acta 12.")
        done = self.step(t00, did, "cerrada", 7)
        self.assertEqual((done["state"], done["code"]), ("cerrada", code))

        self.assertEqual(self.call("GET", "/api/v1/demands", token=t07)[2]["items"], [])
        self.assertEqual(len(self.call("GET", "/api/v1/demands?all=1", token=t07)[2]["items"]), 1)
        self.assertTrue(self.call("GET", "/api/v1/audit/verify", token=tmon)[2]["valid"])

    def test_only_node07_registers(self) -> None:
        status, _, body = self.call("POST", "/api/v1/demands", DEMAND, self.login("op00"))
        self.assertEqual((status, body["error"]["code"]), (403, "permission_denied"))

    def test_stale_version_conflict(self) -> None:
        did = self.call("POST", "/api/v1/demands", DEMAND, self.login("op07"))[2]["id"]
        t00 = self.login("op00")
        self.step(t00, did, "verificada", 1)
        status, _, body = self.call(
            "POST", f"/api/v1/demands/{did}/transition",
            {"target": "pendiente_autorizacion", "expected_version": 1}, t00,
        )
        self.assertEqual((status, body["error"]["code"]), (409, "concurrency_conflict"))

    def test_invalid_transition(self) -> None:
        did = self.call("POST", "/api/v1/demands", DEMAND, self.login("op07"))[2]["id"]
        status, _, body = self.call(
            "POST", f"/api/v1/demands/{did}/transition",
            {"target": "cerrada", "expected_version": 1}, self.login("op00"),
        )
        self.assertEqual((status, body["error"]["code"]), (409, "invalid_transition"))

    def test_area_cannot_read_unassigned_demand(self) -> None:
        did = self.call("POST", "/api/v1/demands", DEMAND, self.login("op07"))[2]["id"]
        self.assertEqual(self.call("GET", f"/api/v1/demands/{did}", token=self.login("salud"))[0], 403)

    def test_audit_verify_is_restricted(self) -> None:
        self.assertEqual(self.call("GET", "/api/v1/audit/verify", token=self.login("op07"))[0], 403)

    def test_audit_chain_covers_auth_events(self) -> None:
        self.login("op07")
        self.call("POST", "/api/v1/login", {"username": "op07", "password": "mala-clave-123"})
        actions = [json.loads(r["payload"])["action"] for r in self.store.read("SELECT payload FROM audit_log")]
        self.assertIn("user_created", actions)
        self.assertIn("login", actions)
        self.assertIn("login_failed", actions)
        self.assertTrue(self.store.verify_audit_chain())


class HardeningTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.t07 = self.login("op07")

    def test_content_type_must_be_json(self) -> None:
        status, _, _ = self.call("POST", "/api/v1/demands", raw=b"x=1", ctype="text/plain", token=self.t07)
        self.assertEqual(status, 415)

    def test_malformed_and_non_object_json(self) -> None:
        self.assertEqual(self.call("POST", "/api/v1/demands", raw=b"{no-json", token=self.t07)[0], 400)
        self.assertEqual(self.call("POST", "/api/v1/demands", raw=b"[1,2]", token=self.t07)[0], 422)
        self.assertEqual(self.call("POST", "/api/v1/demands", raw=b"\xff\xfe", token=self.t07)[0], 400)

    def test_oversized_body_is_rejected_before_reading(self) -> None:
        status, _, _ = self.call("POST", "/api/v1/demands", raw=b"{}", length=MAX_BODY_BYTES + 1, token=self.t07)
        self.assertEqual(status, 413)

    def test_strict_schema(self) -> None:
        extra = {**DEMAND, "state": "cerrada"}                       # mass-assignment
        self.assertEqual(self.call("POST", "/api/v1/demands", extra, self.t07)[0], 422)
        missing = {k: v for k, v in DEMAND.items() if k != "reason"}
        self.assertEqual(self.call("POST", "/api/v1/demands", missing, self.t07)[0], 422)
        for bad in ({"quantity": True}, {"quantity": 2.5}, {"quantity": "50"}, {"alert_level": "azul"}):
            self.assertEqual(self.call("POST", "/api/v1/demands", {**DEMAND, **bad}, self.t07)[0], 422, bad)

    def test_routing_errors(self) -> None:
        self.assertEqual(self.call("GET", "/api/v1/nada", token=self.t07)[0], 404)
        self.assertEqual(self.call("DELETE", "/api/v1/demands", token=self.t07)[0], 405)
        self.assertEqual(self.call("GET", "/api/v1/demands/999", token=self.t07)[0], 404)
        self.assertEqual(self.call("GET", "/api/v1/demands/abc", token=self.t07)[0], 404)

    def test_security_headers(self) -> None:
        _, headers, _ = self.call("GET", "/healthz")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Server"], "sgadr")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])

    def test_internal_errors_do_not_leak_details(self) -> None:
        with mock.patch.object(self.demands, "list_demands", side_effect=RuntimeError("secreto-interno")):
            with self.assertLogs("sgadr.api", level="ERROR"):
                status, _, body = self.call("GET", "/api/v1/demands", token=self.t07)
        self.assertEqual(status, 500)
        self.assertNotIn("secreto-interno", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
