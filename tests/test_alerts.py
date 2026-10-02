"""Pruebas del circuito de alertas: reglas, ciclo de reportes, recordatorios, API y migraciones."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sgadr.domain import (
    Actor, AlertLevel, AlertSource, AlertState, ConcurrencyConflict, DuplicateError,
    InvalidTransition, NewAlert, NewDemand, PermissionDenied, Role, ValidationError,
    VerificationSource,
)
from sgadr.reminders import ReminderWorker
from sgadr.store import _MIGRATIONS, SCHEMA_VERSION, Store

from .support import (
    ALERT_APA, ALERT_MUNI, DEMAND, ApiTestCase, setUpModule, tearDownModule,  # noqa: F401
)

N07 = Actor("op07", Role.NODO_07)
N00 = Actor("op00", Role.NODO_00)
COMITE = Actor("comite", Role.COMITE)
MON = Actor("mon", Role.MONITOREO)
SALUD = Actor("salud", Role.AREA, "Salud")


def apa(municipality: str = "Resistencia", level: AlertLevel = AlertLevel.AMARILLO) -> NewAlert:
    return NewAlert(level, AlertSource.APA, municipality, "Pronóstico de lluvia en 48-72 hs.")


def muni(municipality: str = "Barranqueras", level: AlertLevel = AlertLevel.NARANJA) -> NewAlert:
    return NewAlert(level, AlertSource.MUNICIPIO, municipality, "Crecida del río con anegamiento.",
                    "Intendente Y", "+54 362 4111111")


class AlertRulesTests(ApiTestCase):
    def due(self, view: dict) -> datetime:
        return datetime.fromisoformat(view["next_report_due_at"])

    def test_apa_alert_is_active_immediately_with_level_interval(self) -> None:
        amarillo = self.alerts.register(N07, apa("Resistencia", AlertLevel.AMARILLO))
        rojo = self.alerts.register(N07, apa("Fontana", AlertLevel.ROJO))
        self.assertEqual((amarillo["state"], amarillo["code"]), ("activa", "ALERTA-2026-0001"))
        self.assertEqual(self.due(amarillo), self.clock.now + timedelta(hours=12))
        self.assertEqual(amarillo["report_interval_hours"], 12)
        self.assertEqual(self.due(rojo), self.clock.now + timedelta(hours=6))

    def test_municipal_alert_needs_both_verifications(self) -> None:
        a = self.alerts.register(N07, muni())
        self.assertEqual((a["state"], a["next_report_due_at"]), ("pendiente_verificacion", None))
        a = self.alerts.verify(N00, a["id"], VerificationSource.APA, True, expected_version=1)
        self.assertEqual(a["state"], "pendiente_verificacion")
        a = self.alerts.verify(N00, a["id"], VerificationSource.POLICIA, True, expected_version=2)
        self.assertEqual(a["state"], "activa")
        self.assertEqual(self.due(a), self.clock.now + timedelta(hours=6))  # naranja: 6 h

    def test_negative_verification_discards_and_frees_the_municipality(self) -> None:
        a = self.alerts.register(N07, muni())
        with self.assertRaises(ValidationError):  # descartar exige fundamento
            self.alerts.verify(N00, a["id"], VerificationSource.POLICIA, False, expected_version=1)
        a = self.alerts.verify(N00, a["id"], VerificationSource.POLICIA, False, expected_version=1,
                               note="La policía no constata anegamiento.")
        self.assertEqual(a["state"], "descartada")
        self.assertIsNotNone(a["closed_at"])
        self.alerts.register(N07, muni())  # el municipio puede volver a informar

    def test_verification_cannot_be_repeated_or_applied_to_active_alert(self) -> None:
        a = self.alerts.register(N07, muni())
        self.alerts.verify(N00, a["id"], VerificationSource.APA, True, expected_version=1)
        with self.assertRaises(InvalidTransition):
            self.alerts.verify(N00, a["id"], VerificationSource.APA, True, expected_version=2)
        b = self.alerts.register(N07, apa())
        with self.assertRaises(InvalidTransition):
            self.alerts.verify(N00, b["id"], VerificationSource.APA, True, expected_version=1)
        # Con la policía solo puede fallar por el ESTADO (la alerta ya está activa).
        with self.assertRaises(InvalidTransition):
            self.alerts.verify(N00, b["id"], VerificationSource.POLICIA, True, expected_version=1)
        self.alerts.verify(N00, a["id"], VerificationSource.POLICIA, True, expected_version=2)
        with self.assertRaises(InvalidTransition):  # ya activada tras ambas verificaciones
            self.alerts.verify(N00, a["id"], VerificationSource.POLICIA, False, expected_version=3,
                               note="Intento tardío de desmentir la alerta.")

    def test_role_rules(self) -> None:
        a = self.alerts.register(N07, apa())
        v = a["version"]
        for actor in (N00, COMITE, MON, SALUD):
            with self.assertRaises(PermissionDenied):
                self.alerts.register(actor, apa("Fontana"))
        with self.assertRaises(PermissionDenied):
            self.alerts.verify(N07, a["id"], VerificationSource.APA, True, expected_version=v)
        with self.assertRaises(PermissionDenied):
            self.alerts.mark_center_informed(N07, a["id"], expected_version=v)
        with self.assertRaises(PermissionDenied):
            self.alerts.add_report(N00, a["id"], "Sin novedades graves.", False, expected_version=v)
        with self.assertRaises(PermissionDenied):
            self.alerts.change_level(N00, a["id"], AlertLevel.ROJO, "Escalada de nivel", expected_version=v)

    def test_areas_have_no_access_to_alerts(self) -> None:
        a = self.alerts.register(N07, apa())
        with self.assertRaises(PermissionDenied):
            self.alerts.get(SALUD, a["id"])
        with self.assertRaises(PermissionDenied):
            self.alerts.list_alerts(SALUD)

    def test_contact_is_hidden_from_node00_and_monitoreo(self) -> None:
        a = self.alerts.register(N07, muni())
        self.assertEqual(self.alerts.get(N07, a["id"])["contact_phone"], "+54 362 4111111")
        for actor in (N00, MON):
            view = self.alerts.get(actor, a["id"])
            self.assertNotIn("contact_phone", view)
            self.assertNotIn("contact_name", view)
        self.assertIn("contact_phone", self.alerts.get(COMITE, a["id"]))

    def test_internal_fields_never_leak(self) -> None:
        view = self.alerts.get(N07, self.alerts.register(N07, apa())["id"])
        self.assertNotIn("municipality_key", view)
        self.assertNotIn("overdue_flagged_for", view)

    def test_contact_rules_by_source(self) -> None:
        with self.assertRaises(ValidationError):
            self.alerts.register(N07, NewAlert(AlertLevel.ROJO, AlertSource.APA, "Fontana",
                                               "Cota de evacuación alcanzada.", "X", "+54 362 400000"))
        with self.assertRaises(ValidationError):
            self.alerts.register(N07, NewAlert(AlertLevel.ROJO, AlertSource.MUNICIPIO, "Fontana",
                                               "Cota de evacuación alcanzada."))
        with self.assertRaises(ValidationError):
            self.alerts.register(N07, NewAlert(AlertLevel.ROJO, AlertSource.MUNICIPIO, "Fontana",
                                               "Cota de evacuación alcanzada.", "X", "abc"))

    def test_one_live_alert_per_municipality_ignoring_accents_and_case(self) -> None:
        a = self.alerts.register(N07, apa("Presidencia Roque Sáenz Peña"))
        with self.assertRaises(DuplicateError):
            self.alerts.register(N07, muni("  presidencia roque SAENZ  peña "))
        self.alerts.add_report(N07, a["id"], "La situación se normalizó.", True, expected_version=1)
        self.alerts.register(N07, apa("Presidencia Roque Sáenz Peña"))  # ya cerrada: se admite otra

    def test_duplicate_rolls_back_the_code_counter(self) -> None:
        self.alerts.register(N07, apa("Resistencia"))
        with self.assertRaises(DuplicateError):
            self.alerts.register(N07, apa("Resistencia"))
        self.assertEqual(self.alerts.register(N07, apa("Fontana"))["code"], "ALERTA-2026-0002")

    def test_optimistic_locking(self) -> None:
        a = self.alerts.register(N07, apa())
        self.alerts.add_report(N07, a["id"], "Sin novedades graves.", False, expected_version=1)
        with self.assertRaises(ConcurrencyConflict):
            self.alerts.add_report(N07, a["id"], "Otro operador carga lo mismo.", False, expected_version=1)

    def test_audit_chain_covers_alert_events(self) -> None:
        a = self.alerts.register(N07, muni())
        self.alerts.verify(N00, a["id"], VerificationSource.APA, True, expected_version=1)
        self.alerts.verify(N00, a["id"], VerificationSource.POLICIA, True, expected_version=2)
        self.alerts.mark_center_informed(N00, a["id"], expected_version=3)
        actions = [json.loads(r["payload"]).get("action") for r in self.store.read("SELECT payload FROM audit_log")]
        for expected in ("alert_register", "alert_verified", "alert_center_informed"):
            self.assertIn(expected, actions)
        self.assertTrue(self.store.verify_audit_chain())


class ReportCycleTests(ApiTestCase):
    def test_overdue_is_computed_and_reset_by_a_report(self) -> None:
        a = self.alerts.register(N07, apa())
        self.assertFalse(self.alerts.get(N07, a["id"])["overdue"])
        self.clock.advance(timedelta(hours=12, minutes=30))
        view = self.alerts.get(N07, a["id"])
        self.assertEqual((view["overdue"], view["overdue_minutes"]), (True, 30))
        self.assertEqual(len(self.alerts.list_alerts(N07, only_overdue=True)), 1)
        view = self.alerts.add_report(N07, a["id"], "El municipio informa estado estable.", False,
                                      expected_version=1)
        self.assertFalse(view["overdue"])
        self.assertEqual(datetime.fromisoformat(view["next_report_due_at"]),
                         self.clock.now + timedelta(hours=12))
        self.assertEqual(self.alerts.list_alerts(N07, only_overdue=True), [])

    def test_lowered_report_closes_the_communication(self) -> None:
        a = self.alerts.register(N07, apa())
        view = self.alerts.add_report(N07, a["id"], "La alerta bajó, ríos en descenso.", True,
                                      expected_version=1)
        self.assertEqual(view["state"], AlertState.CERRADA)
        self.assertIsNone(view["next_report_due_at"])
        self.assertEqual(len(view["reports"]), 1)
        self.assertTrue(view["reports"][0]["alert_lowered"])
        with self.assertRaises(InvalidTransition):
            self.alerts.add_report(N07, a["id"], "Reporte posterior al cierre.", False, expected_version=2)
        self.assertEqual(self.alerts.list_alerts(N07), [])                 # solo vigentes
        self.assertEqual(len(self.alerts.list_alerts(N07, only_open=False)), 1)

    def test_flag_overdue_notifies_once_per_cycle(self) -> None:
        a = self.alerts.register(N07, apa())
        self.assertEqual(self.alerts.flag_overdue(), [])
        self.clock.advance(timedelta(hours=12))
        flagged = self.alerts.flag_overdue()
        self.assertEqual([f["code"] for f in flagged], [a["code"]])
        self.assertEqual(self.alerts.flag_overdue(), [])                   # idempotente
        self.clock.advance(timedelta(hours=1))
        self.assertEqual(self.alerts.flag_overdue(), [])
        self.alerts.add_report(N07, a["id"], "Sin novedades graves.", False, expected_version=1)
        self.clock.advance(timedelta(hours=12))
        self.assertEqual(len(self.alerts.flag_overdue()), 1)               # nuevo ciclo, nuevo aviso
        entries = [json.loads(r["payload"]) for r in self.store.read("SELECT payload FROM audit_log")]
        overdue = [e for e in entries if e.get("action") == "alert_report_overdue"]
        self.assertEqual(len(overdue), 2)
        self.assertEqual(overdue[0]["actor"], "system")

    def test_flagging_does_not_invalidate_in_flight_edits(self) -> None:
        a = self.alerts.register(N07, apa())
        self.clock.advance(timedelta(hours=13))
        self.alerts.flag_overdue()
        self.alerts.add_report(N07, a["id"], "Reporte con la versión original.", False, expected_version=1)

    def test_level_change_resets_cycle_and_requires_informing_the_center_again(self) -> None:
        a = self.alerts.register(N07, apa(level=AlertLevel.AMARILLO))
        self.alerts.mark_center_informed(N00, a["id"], expected_version=1)
        with self.assertRaises(InvalidTransition):
            self.alerts.mark_center_informed(N00, a["id"], expected_version=2)
        with self.assertRaises(ValidationError):
            self.alerts.change_level(N07, a["id"], AlertLevel.AMARILLO, "Sin cambio real", expected_version=2)
        with self.assertRaises(ValidationError):
            self.alerts.change_level(N07, a["id"], AlertLevel.NARANJA, "ok", expected_version=2)
        self.clock.advance(timedelta(hours=3))
        view = self.alerts.change_level(N07, a["id"], AlertLevel.NARANJA,
                                        "APA eleva a naranja por lluvia acumulada.", expected_version=2)
        self.assertEqual((view["level"], view["report_interval_hours"]), ("naranja", 6))
        self.assertEqual(datetime.fromisoformat(view["next_report_due_at"]),
                         self.clock.now + timedelta(hours=6))
        self.assertIsNone(view["center_informed_at"])
        self.alerts.mark_center_informed(N00, a["id"], expected_version=3)


class DemandLinkTests(ApiTestCase):
    def new_demand(self, municipality: str, level: AlertLevel | None = None) -> NewDemand:
        return NewDemand(level, municipality, "Barrio Norte", "Colchones", 5,
                         "Familias evacuadas sin colchones.", "Intendente X", "+54 362 4000000")

    def test_demand_links_to_the_active_alert_and_inherits_its_level(self) -> None:
        a = self.alerts.register(N07, apa("Presidencia Roque Sáenz Peña", AlertLevel.ROJO))
        d = self.demands.register(N07, self.new_demand("presidencia roque saenz pena"))
        self.assertEqual((d["alert_id"], d["alert_level"]), (a["id"], "rojo"))

    def test_demand_without_alert_requires_an_explicit_level(self) -> None:
        with self.assertRaises(ValidationError):
            self.demands.register(N07, self.new_demand("Fontana"))
        d = self.demands.register(N07, self.new_demand("Fontana", AlertLevel.AMARILLO))
        self.assertIsNone(d["alert_id"])
        self.assertEqual(d["alert_level"], "amarillo")

    def test_pending_or_closed_alerts_are_not_linked(self) -> None:
        self.alerts.register(N07, muni("Barranqueras"))                    # pendiente de verificación
        with self.assertRaises(ValidationError):
            self.demands.register(N07, self.new_demand("Barranqueras"))


class ReminderWorkerTests(ApiTestCase):
    def test_run_once_notifies_each_overdue_alert_once(self) -> None:
        self.alerts.register(N07, apa("Resistencia"))
        self.clock.advance(timedelta(hours=13))
        seen: list[str] = []
        worker = ReminderWorker(self.alerts, lambda a: seen.append(a["code"]))
        self.assertEqual(worker.run_once(), 1)
        self.assertEqual(worker.run_once(), 0)
        self.assertEqual(seen, ["ALERTA-2026-0001"])

    def test_a_failing_channel_does_not_stop_other_notifications(self) -> None:
        self.alerts.register(N07, apa("Resistencia"))
        self.alerts.register(N07, apa("Fontana"))
        self.clock.advance(timedelta(hours=13))
        calls: list[str] = []

        def flaky(alert: dict) -> None:
            calls.append(alert["code"])
            if len(calls) == 1:
                raise RuntimeError("canal caído")

        with self.assertLogs("sgadr.reminders", level=logging.ERROR):
            self.assertEqual(ReminderWorker(self.alerts, flaky).run_once(), 2)
        self.assertEqual(len(calls), 2)

    def test_default_notifier_writes_a_warning(self) -> None:
        self.alerts.register(N07, apa())
        self.clock.advance(timedelta(hours=13))
        with self.assertLogs("sgadr.reminders", level=logging.WARNING) as logs:
            ReminderWorker(self.alerts).run_once()
        self.assertIn("REPORTE VENCIDO", logs.output[0])

    def test_background_thread_runs_and_stops(self) -> None:
        self.alerts.register(N07, apa())
        self.clock.advance(timedelta(hours=13))
        fired = threading.Event()
        worker = ReminderWorker(self.alerts, lambda a: fired.set(), interval_s=0.05)
        worker.start()
        try:
            self.assertTrue(fired.wait(timeout=3), "el worker no notificó a tiempo")
        finally:
            worker.stop()
        self.assertFalse(worker._thread is not None and worker._thread.is_alive())

    def test_invalid_interval(self) -> None:
        with self.assertRaises(ValueError):
            ReminderWorker(self.alerts, interval_s=0)


class AlertApiTests(ApiTestCase):
    def post(self, path: str, body: dict, token: str) -> tuple[int, dict]:
        status, _, data = self.call("POST", path, body, token)
        return status, data

    def test_full_alert_circuit_over_http(self) -> None:
        t07, t00, tmon = self.login("op07"), self.login("op00"), self.login("mon")
        status, a = self.post("/api/v1/alerts", ALERT_MUNI, t07)
        self.assertEqual((status, a["state"]), (201, "pendiente_verificacion"))
        aid, base = a["id"], f"/api/v1/alerts/{a['id']}"

        status, a = self.post(f"{base}/verify", {"source": "apa", "confirmed": True, "expected_version": 1}, t00)
        self.assertEqual(status, 200, a)
        self.assertNotIn("contact_phone", a)                               # el Nodo 00 no ve al municipio
        status, a = self.post(f"{base}/verify", {"source": "policia", "confirmed": True, "expected_version": 2}, t00)
        self.assertEqual((status, a["state"]), (200, "activa"))
        status, a = self.post(f"{base}/center-informed", {"expected_version": 3}, t00)
        self.assertEqual((status, a["center_informed_at"] is not None), (200, True))
        status, a = self.post(f"{base}/reports",
                              {"municipal_status": "Familias evacuadas, agua en descenso.",
                               "alert_lowered": False, "expected_version": 4}, t07)
        self.assertEqual(status, 200, a)

        self.clock.advance(timedelta(hours=7))
        items = self.call("GET", "/api/v1/alerts?overdue=1", token=tmon)[2]["items"]
        self.assertEqual([i["id"] for i in items], [aid])
        self.assertNotIn("contact_phone", items[0])

        status, a = self.post(f"{base}/reports",
                              {"municipal_status": "La alerta bajó en todo el municipio.",
                               "alert_lowered": True, "expected_version": 5}, t07)
        self.assertEqual((status, a["state"]), (200, "cerrada"))
        self.assertEqual(self.call("GET", "/api/v1/alerts", token=t07)[2]["items"], [])
        self.assertEqual(len(self.call("GET", "/api/v1/alerts?all=1", token=t07)[2]["items"]), 1)
        detail = self.call("GET", base, token=t07)[2]
        self.assertEqual(len(detail["reports"]), 2)

    def test_duplicate_alert_is_a_409(self) -> None:
        t07 = self.login("op07")
        self.assertEqual(self.post("/api/v1/alerts", ALERT_APA, t07)[0], 201)
        status, body = self.post("/api/v1/alerts", ALERT_APA, t07)
        self.assertEqual((status, body["error"]["code"]), (409, "duplicate"))

    def test_level_change_over_http(self) -> None:
        t07 = self.login("op07")
        a = self.post("/api/v1/alerts", ALERT_APA, t07)[1]
        status, body = self.post(f"/api/v1/alerts/{a['id']}/level",
                                 {"level": "rojo", "note": "APA informa cota de evacuación.",
                                  "expected_version": 1}, t07)
        self.assertEqual((status, body["level"], body["report_interval_hours"]), (200, "rojo", 6))

    def test_permissions_and_authentication(self) -> None:
        self.assertEqual(self.call("GET", "/api/v1/alerts")[0], 401)
        self.assertEqual(self.call("GET", "/api/v1/alerts", token=self.login("salud"))[0], 403)
        status, body = self.post("/api/v1/alerts", ALERT_APA, self.login("op00"))
        self.assertEqual((status, body["error"]["code"]), (403, "permission_denied"))

    def test_strict_schema_on_alert_endpoints(self) -> None:
        t07, t00 = self.login("op07"), self.login("op00")
        self.assertEqual(self.post("/api/v1/alerts", {**ALERT_APA, "state": "cerrada"}, t07)[0], 422)
        self.assertEqual(self.post("/api/v1/alerts", {**ALERT_APA, "level": "azul"}, t07)[0], 422)
        self.assertEqual(self.post("/api/v1/alerts", {**ALERT_APA, "source": "radio"}, t07)[0], 422)
        a = self.post("/api/v1/alerts", ALERT_MUNI, t07)[1]
        base = f"/api/v1/alerts/{a['id']}"
        for bad in ({"source": "apa", "confirmed": "si", "expected_version": 1},
                    {"source": "apa", "confirmed": True},
                    {"source": "apa", "confirmed": True, "expected_version": True},
                    {"source": "bomberos", "confirmed": True, "expected_version": 1}):
            self.assertEqual(self.post(f"{base}/verify", bad, t00)[0], 422, bad)

    def test_demand_inherits_level_from_active_alert_over_http(self) -> None:
        t07 = self.login("op07")
        alert = self.post("/api/v1/alerts", {**ALERT_APA, "level": "rojo"}, t07)[1]
        body = {k: v for k, v in DEMAND.items() if k != "alert_level"}
        status, demand = self.post("/api/v1/demands", body, t07)
        self.assertEqual((status, demand["alert_level"], demand["alert_id"]), (201, "rojo", alert["id"]))
        status, err = self.post("/api/v1/demands", {**body, "municipality": "Fontana"}, t07)
        self.assertEqual((status, err["error"]["code"]), (422, "validation_error"))


class MigrationTests(unittest.TestCase):
    def test_fresh_database_is_at_latest_version(self) -> None:
        store = Store(":memory:")
        try:
            self.assertEqual(store.read("PRAGMA user_version")[0][0], SCHEMA_VERSION)
        finally:
            store.close()

    def test_upgrade_from_v1_preserves_existing_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript(_MIGRATIONS[0])
            conn.execute("PRAGMA user_version = 1")
            conn.execute(
                "INSERT INTO demands (code, version, state, alert_level, municipality, locality,"
                " resource_type, quantity, reason, contact_name, contact_phone, created_by,"
                " created_at, updated_at) VALUES ('ENOS-2026-0001', 1, 'recibida', 'rojo', 'R', 'L',"
                " 'C', 1, 'motivo suficiente', 'N', '123456', 'u', 't', 't')"
            )
            conn.commit()
            conn.close()
            store = Store(path)
            try:
                self.assertEqual(store.read("PRAGMA user_version")[0][0], SCHEMA_VERSION)
                row = store.read("SELECT code, alert_id FROM demands")[0]
                self.assertEqual((row["code"], row["alert_id"]), ("ENOS-2026-0001", None))
            finally:
                store.close()
            Store(path).close()                                            # reabrir no reaplica nada

    def test_database_from_a_newer_version_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.db"
            conn = sqlite3.connect(path)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
            conn.close()
            with self.assertRaises(RuntimeError):
                Store(path)


if __name__ == "__main__":
    unittest.main()
