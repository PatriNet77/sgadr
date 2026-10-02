"""Pruebas de la administración de cuentas: separación de funciones, claves temporales y alta/baja."""

from __future__ import annotations

import unittest

from sgadr.domain import Actor, PermissionDenied, Role, ValidationError

from .support import DEMAND, PASSWORD, ApiTestCase, setUpModule, tearDownModule  # noqa: F401

TEMP = "clave-temporal-9"
NEW = "clave-definitiva-77"


class AdminSeparationTests(ApiTestCase):
    def test_admin_cannot_read_operational_data(self) -> None:
        t = self.login("admin")
        for path in ("/api/v1/demands", "/api/v1/alerts", "/api/v1/audit", "/api/v1/audit/verify"):
            self.assertEqual(self.call("GET", path, token=t)[0], 403, path)

    def test_admin_cannot_register_or_transition(self) -> None:
        t = self.login("admin")
        self.assertEqual(self.call("POST", "/api/v1/demands", DEMAND, t)[0], 403)
        status, _, body = self.call("POST", "/api/v1/alerts", {
            "level": "amarillo", "source": "apa", "municipality": "Resistencia", "summary": "Prueba de rol."}, t)
        self.assertEqual(status, 403, body)

    def test_only_admin_manages_accounts(self) -> None:
        for user in ("op07", "op00", "comite", "mon", "salud"):
            t = self.login(user)
            self.assertEqual(self.call("GET", "/api/v1/users", token=t)[0], 403, user)
            status, _, _ = self.call("POST", "/api/v1/users", {
                "username": "nuevo1", "temporary_password": TEMP, "role": "nodo_07"}, t)
            self.assertEqual(status, 403, user)

    def test_user_list_never_exposes_hashes(self) -> None:
        status, _, body = self.call("GET", "/api/v1/users", token=self.login("admin"))
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["items"]), 6)
        for item in body["items"]:
            self.assertEqual(set(item), {"username", "role", "area", "active", "created_at", "locked", "must_change_password"})


class TemporaryPasswordTests(ApiTestCase):
    def create(self, **over: object) -> None:
        body = {"username": "nuevo1", "temporary_password": TEMP, "role": "nodo_07", **over}
        status, _, resp = self.call("POST", "/api/v1/users", body, self.login("admin"))
        self.assertEqual(status, 201, resp)

    def test_new_account_must_change_password_before_operating(self) -> None:
        self.create()
        status, _, body = self.call("POST", "/api/v1/login", {"username": "nuevo1", "password": TEMP})
        self.assertTrue(body["must_change_password"])
        t = body["token"]
        status, _, err = self.call("GET", "/api/v1/demands", token=t)
        self.assertEqual((status, err["error"]["code"]), (403, "password_change_required"))
        self.assertEqual(self.call("GET", "/api/v1/me", token=t)[0], 200)  # puede ver su sesión
        self.assertEqual(self.call("GET", "/api/v1/meta", token=t)[0], 403)

        status, _, resp = self.call("POST", "/api/v1/password", {"current_password": TEMP, "new_password": NEW}, t)
        self.assertEqual(status, 200, resp)
        self.assertEqual(self.call("GET", "/api/v1/demands", token=t)[0], 200)
        self.assertFalse(self.call("GET", "/api/v1/me", token=t)[2]["must_change_password"])

    def test_change_password_rules(self) -> None:
        t = self.login("op07")
        bad = [
            {"current_password": "incorrecta-123", "new_password": NEW},
            {"current_password": PASSWORD, "new_password": PASSWORD},
            {"current_password": PASSWORD, "new_password": "corta"},
        ]
        for body in bad:
            self.assertEqual(self.call("POST", "/api/v1/password", body, t)[0], 422, body)
        self.assertEqual(self.call("POST", "/api/v1/password", {"current_password": 1, "new_password": NEW}, t)[0], 422)

    def test_change_revokes_other_sessions_and_old_password(self) -> None:
        t1, t2 = self.login("op07"), self.login("op07")
        self.assertEqual(self.call("POST", "/api/v1/password", {"current_password": PASSWORD, "new_password": NEW}, t1)[0], 200)
        self.assertEqual(self.call("GET", "/api/v1/demands", token=t1)[0], 200)
        self.assertEqual(self.call("GET", "/api/v1/demands", token=t2)[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/login", {"username": "op07", "password": PASSWORD})[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/login", {"username": "op07", "password": NEW})[0], 200)

    def test_area_account_requires_valid_area(self) -> None:
        admin = self.login("admin")
        status, _, _ = self.call("POST", "/api/v1/users", {"username": "vial", "temporary_password": TEMP, "role": "area"}, admin)
        self.assertEqual(status, 422)
        self.create(username="vial", role="area", area="Vialidad Provincial")

    def test_duplicate_and_unknown_keys_and_role(self) -> None:
        self.create()
        admin = self.login("admin")
        self.assertEqual(self.call("POST", "/api/v1/users", {"username": "nuevo1", "temporary_password": TEMP, "role": "nodo_07"}, admin)[0], 422)
        self.assertEqual(self.call("POST", "/api/v1/users", {"username": "otro22", "temporary_password": TEMP, "role": "root"}, admin)[0], 422)
        self.assertEqual(self.call("POST", "/api/v1/users", {"username": "otro22", "temporary_password": TEMP, "role": "nodo_07", "active": True}, admin)[0], 422)
        self.assertEqual(self.call("POST", "/api/v1/users", {"username": "Mayus", "temporary_password": TEMP, "role": "nodo_07"}, admin)[0], 422)


class LifecycleTests(ApiTestCase):
    def test_deactivate_revokes_sessions_and_reactivate_restores(self) -> None:
        admin, t = self.login("admin"), self.login("op07")
        self.assertEqual(self.call("POST", "/api/v1/users/op07/active", {"active": False}, admin)[0], 200)
        self.assertEqual(self.call("GET", "/api/v1/demands", token=t)[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/login", {"username": "op07", "password": PASSWORD})[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/users/op07/active", {"active": False}, admin)[0], 422)
        self.assertEqual(self.call("POST", "/api/v1/users/op07/active", {"active": True}, admin)[0], 200)
        self.assertEqual(self.call("POST", "/api/v1/login", {"username": "op07", "password": PASSWORD})[0], 200)

    def test_cannot_deactivate_self_or_last_admin(self) -> None:
        admin = self.login("admin")
        self.assertEqual(self.call("POST", "/api/v1/users/admin/active", {"active": False}, admin)[0], 422)
        self.auth.create_user("admin2", PASSWORD, Role.ADMIN)
        a2 = self.login("admin2")
        self.assertEqual(self.call("POST", "/api/v1/users/admin/active", {"active": False}, a2)[0], 200)
        # admin2 queda como única cuenta administradora: ni él mismo ni nadie puede dejar el sistema sin ninguna.
        self.assertEqual(self.call("POST", "/api/v1/users/admin2/active", {"active": False}, a2)[0], 422)

    def test_active_requires_boolean(self) -> None:
        admin = self.login("admin")
        for bad in ("false", 0, None):
            self.assertEqual(self.call("POST", "/api/v1/users/op07/active", {"active": bad}, admin)[0], 422, bad)

    def test_reset_password_unlocks_and_forces_change(self) -> None:
        for _ in range(3):  # max_attempts=3 en la base de pruebas
            self.call("POST", "/api/v1/login", {"username": "op07", "password": "mala-clave-123"})
        self.assertEqual(self.call("POST", "/api/v1/login", {"username": "op07", "password": PASSWORD})[0], 401)  # bloqueado
        admin = self.login("admin")
        listed = {u["username"]: u for u in self.call("GET", "/api/v1/users", token=admin)[2]["items"]}
        self.assertTrue(listed["op07"]["locked"])
        old = self.login("op00")
        self.assertEqual(self.call("POST", "/api/v1/users/op07/password", {"temporary_password": TEMP}, admin)[0], 200)
        status, _, body = self.call("POST", "/api/v1/login", {"username": "op07", "password": TEMP})
        self.assertEqual((status, body["must_change_password"]), (200, True))
        self.assertEqual(self.call("GET", "/api/v1/demands", token=old)[0], 200)  # otras personas no se ven afectadas

    def test_reset_rules(self) -> None:
        admin = self.login("admin")
        self.assertEqual(self.call("POST", "/api/v1/users/admin/password", {"temporary_password": TEMP}, admin)[0], 422)
        self.assertEqual(self.call("POST", "/api/v1/users/noexiste/password", {"temporary_password": TEMP}, admin)[0], 404)
        self.assertEqual(self.call("POST", "/api/v1/users/op07/password", {"temporary_password": "corta"}, admin)[0], 422)

    def test_every_change_is_audited_with_author_and_no_secret(self) -> None:
        admin = self.login("admin")
        self.call("POST", "/api/v1/users", {"username": "nuevo1", "temporary_password": TEMP, "role": "nodo_07"}, admin)
        self.call("POST", "/api/v1/users/nuevo1/password", {"temporary_password": NEW}, admin)
        self.call("POST", "/api/v1/users/nuevo1/active", {"active": False}, admin)
        self.call("POST", "/api/v1/users/nuevo1/active", {"active": True}, admin)
        entries = [r["entry"] for r in self.demands.audit_recent(50)]
        actions = {(e["action"], e.get("by")) for e in entries if e.get("user") == "nuevo1"}
        self.assertEqual(actions, {("user_created", "admin"), ("password_reset", "admin"),
                                   ("user_deactivated", "admin"), ("user_reactivated", "admin")})
        self.assertNotIn(TEMP, repr(entries))
        self.assertNotIn(NEW, repr(entries))
        self.assertTrue(self.demands.verify_audit())

    def test_service_enforces_admin_role_without_api(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.auth.admin_create_user(Actor("op07", Role.NODO_07), "zzz", TEMP, Role.NODO_07, None)
        with self.assertRaises(PermissionDenied):
            self.auth.list_users(Actor("mon", Role.MONITOREO))
        with self.assertRaises(ValidationError):
            self.auth.admin_create_user(Actor("admin", Role.ADMIN), "zzz", "corta", Role.NODO_07, None)


if __name__ == "__main__":
    unittest.main()
