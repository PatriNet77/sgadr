"""Pruebas del núcleo SGADR (ejecutar: python -m unittest discover -s tests -t .)."""

from __future__ import annotations

import sqlite3
import unittest

from sgadr.domain import (
    Actor, AlertLevel, ConcurrencyConflict, DemandState as S, InvalidTransition,
    NewDemand, PermissionDenied, Role, ValidationError,
)
from sgadr.security import hash_password, verify_password
from sgadr.service import DemandService
from sgadr.store import Store

N07 = Actor("op07", Role.NODO_07)
N00 = Actor("op00", Role.NODO_00)
COMITE = Actor("comite", Role.COMITE)
SALUD = Actor("salud", Role.AREA, "Salud")
VIALIDAD = Actor("vial", Role.AREA, "Vialidad")


def _demand() -> NewDemand:
    return NewDemand(AlertLevel.NARANJA, "Resistencia", "Barrio Norte", "Colchones", 50,
                     "Anegamiento con familias evacuadas.", "Intendente X", "+54 362 4000000")


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.svc = DemandService(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def _advance(self, actor: Actor, did: int, target: S, **kw: object) -> dict:
        version = self.store.read("SELECT version FROM demands WHERE id=?", (did,))[0]["version"]
        return self.svc.transition(actor, did, target, expected_version=version, **kw)  # type: ignore[arg-type]

    def test_full_circuit_and_audit_chain(self) -> None:
        did = self.svc.register(N07, _demand())["id"]
        self._advance(N00, did, S.VERIFICADA)
        self._advance(N00, did, S.PENDIENTE_AUTORIZACION)
        self._advance(COMITE, did, S.AUTORIZADA)
        self._advance(N00, did, S.ASIGNADA, assigned_area="Salud")
        self._advance(SALUD, did, S.EN_EJECUCION)
        self._advance(SALUD, did, S.RESPONDIDA, response_detail="Entregados 50 colchones, acta 12.")
        final = self._advance(N00, did, S.CERRADA)
        self.assertEqual(final["state"], "cerrada")
        self.assertTrue(self.svc.verify_audit())

    def test_only_node07_registers(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.svc.register(N00, _demand())

    def test_invalid_transition_and_wrong_role(self) -> None:
        did = self.svc.register(N07, _demand())["id"]
        with self.assertRaises(InvalidTransition):
            self._advance(COMITE, did, S.AUTORIZADA)
        with self.assertRaises(PermissionDenied):
            self._advance(N07, did, S.VERIFICADA)

    def test_optimistic_locking(self) -> None:
        did = self.svc.register(N07, _demand())["id"]
        with self.assertRaises(ConcurrencyConflict):
            self.svc.transition(N00, did, S.VERIFICADA, expected_version=99)

    def test_role_based_field_hiding(self) -> None:
        did = self.svc.register(N07, _demand())["id"]
        self.assertNotIn("contact_phone", self.svc.get(N00, did))
        self.assertIn("contact_phone", self.svc.get(N07, did))
        self.assertNotIn("assigned_area", self.svc.get(N07, did))

    def test_area_only_sees_and_acts_on_own_demands(self) -> None:
        did = self.svc.register(N07, _demand())["id"]
        for actor, target, kw in ((N00, S.VERIFICADA, {}), (N00, S.PENDIENTE_AUTORIZACION, {}),
                                  (COMITE, S.AUTORIZADA, {}),
                                  (N00, S.ASIGNADA, {"assigned_area": "Salud"})):
            self._advance(actor, did, target, **kw)
        with self.assertRaises(PermissionDenied):
            self._advance(VIALIDAD, did, S.EN_EJECUCION)
        self.assertEqual(self.svc.list_demands(VIALIDAD), [])
        self.assertEqual(len(self.svc.list_demands(SALUD)), 1)

    def test_mandatory_fields_per_transition(self) -> None:
        did = self.svc.register(N07, _demand())["id"]
        with self.assertRaises(ValidationError):
            self._advance(N00, did, S.RECHAZADA)  # exige fundamento

    def test_audit_log_is_immutable(self) -> None:
        self.svc.register(N07, _demand())
        with self.assertRaises(sqlite3.DatabaseError), self.store.tx() as conn:
            conn.execute("UPDATE audit_log SET payload = 'x'")

    def test_input_validation(self) -> None:
        bad = NewDemand(AlertLevel.ROJO, "A", "B", "C", 0, "motivo suficiente", "N", "abc")
        with self.assertRaises(ValidationError):
            self.svc.register(N07, bad)

    def test_password_hashing(self) -> None:
        stored = hash_password("una-clave-larga-123")
        self.assertTrue(verify_password("una-clave-larga-123", stored))
        self.assertFalse(verify_password("otra-clave-larga-1", stored))
        self.assertFalse(verify_password("x", "formato-invalido"))


if __name__ == "__main__":
    unittest.main()
