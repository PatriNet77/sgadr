"""Persistencia SQLite (stdlib) con transacciones atómicas y bitácora inmutable.

La bitácora encadena cada registro con el hash del anterior (SHA-256) y está
protegida por triggers que impiden UPDATE/DELETE: toda alteración es detectable.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

GENESIS: Final = "0" * 64

_V1: Final = """
CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS demands (
    id            INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    version       INTEGER NOT NULL,
    state         TEXT NOT NULL,
    alert_level   TEXT NOT NULL CHECK (alert_level IN ('amarillo','naranja','rojo')),
    municipality  TEXT NOT NULL,
    locality      TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    reason        TEXT NOT NULL,
    contact_name  TEXT NOT NULL,
    contact_phone TEXT NOT NULL,
    assigned_area TEXT,
    response_detail TEXT,
    created_by    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS users (
    username        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL,
    area            TEXT,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS audit_log (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash TEXT NOT NULL,
    payload   TEXT NOT NULL,
    hash      TEXT NOT NULL UNIQUE
) STRICT;

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log es inmutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log es inmutable'); END;
"""

# v2: circuito de alertas (amarillo/naranja/rojo) y vínculo de cada demanda con la alerta vigente.
_V2: Final = """
CREATE TABLE IF NOT EXISTS alerts (
    id                 INTEGER PRIMARY KEY,
    code               TEXT NOT NULL UNIQUE,
    version            INTEGER NOT NULL,
    state              TEXT NOT NULL CHECK (state IN
                         ('pendiente_verificacion','activa','cerrada','descartada')),
    level              TEXT NOT NULL CHECK (level IN ('amarillo','naranja','rojo')),
    source             TEXT NOT NULL CHECK (source IN ('apa','municipio')),
    municipality       TEXT NOT NULL,
    municipality_key   TEXT NOT NULL,
    summary            TEXT NOT NULL,
    contact_name       TEXT,
    contact_phone      TEXT,
    apa_verified_at    TEXT,
    police_verified_at TEXT,
    center_informed_at TEXT,
    activated_at       TEXT,
    next_report_due_at TEXT,
    overdue_flagged_for TEXT,
    closed_at          TEXT,
    created_by         TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
) STRICT;

-- Invariante: una sola alerta vigente por municipio (los cambios de nivel se hacen sobre ella).
CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_live_municipality ON alerts (municipality_key)
    WHERE state IN ('pendiente_verificacion', 'activa');
CREATE INDEX IF NOT EXISTS ix_alert_due ON alerts (next_report_due_at) WHERE state = 'activa';

CREATE TABLE IF NOT EXISTS alert_reports (
    id               INTEGER PRIMARY KEY,
    alert_id         INTEGER NOT NULL REFERENCES alerts(id),
    reported_at      TEXT NOT NULL,
    reported_by      TEXT NOT NULL,
    municipal_status TEXT NOT NULL,
    alert_lowered    INTEGER NOT NULL CHECK (alert_lowered IN (0, 1)),
    level_at_report  TEXT NOT NULL
) STRICT;

ALTER TABLE demands ADD COLUMN alert_id INTEGER REFERENCES alerts(id);
"""

# v3: clave temporal (la persona debe cambiarla en su primer ingreso tras un alta o restablecimiento).
_V3: Final = """
ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0
    CHECK (must_change_password IN (0, 1));
"""

# Índice i -> versión i+1. Solo se agregan al final; nunca se editan las ya publicadas.
_MIGRATIONS: Final[tuple[str, ...]] = (_V1, _V2, _V3)
SCHEMA_VERSION: Final = len(_MIGRATIONS)


def _digest(prev_hash: str, payload: str) -> str:
    return hashlib.sha256(f"{prev_hash}{payload}".encode()).hexdigest()


class Store:
    """Acceso a datos: una conexión por instancia, transacciones BEGIN IMMEDIATE.

    La conexión se comparte entre hilos del servidor; un RLock serializa todo
    acceso (lecturas y escrituras) para que una transacción nunca se intercale
    con otra operación sobre la misma conexión.
    """

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.RLock()
        if str(path) != ":memory:":
            # Se crea el archivo con permisos 0600 ANTES de abrirlo: sin ventana de
            # exposición. Falla rápido (OSError) si el directorio no es escribible.
            os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        try:
            self._migrate()
        except BaseException:
            self._conn.close()  # no dejar la conexión abierta si la base no es utilizable
            raise

    def _migrate(self) -> None:
        """Aplica las migraciones pendientes, cada una atómica junto con su `user_version`."""
        with self._lock:
            current: int = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"La base es de una versión más nueva ({current}) que este software ({SCHEMA_VERSION})."
                )
            for version, script in enumerate(_MIGRATIONS, start=1):
                if version <= current:
                    continue
                try:
                    self._conn.executescript(
                        f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
                    )
                except sqlite3.Error:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transacción de escritura serializada; revierte ante cualquier excepción."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def read(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def append_audit(conn: sqlite3.Connection, record: dict[str, object]) -> None:
        """Agrega un registro encadenado. Debe llamarse dentro de `tx()`."""
        last = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        conn.execute(
            "INSERT INTO audit_log (prev_hash, payload, hash) VALUES (?, ?, ?)",
            (prev, payload, _digest(prev, payload)),
        )

    def recent_audit(self, limit: int) -> list[dict[str, object]]:
        """Últimas entradas de la bitácora (más nuevas primero), con el hash abreviado."""
        rows = self.read(
            "SELECT seq, hash, payload FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,)
        )
        return [
            {"seq": r["seq"], "hash": r["hash"][:12], "entry": json.loads(r["payload"])}
            for r in rows
        ]

    def verify_audit_chain(self) -> bool:
        """Recalcula toda la cadena; False ante cualquier alteración o hueco."""
        prev = GENESIS
        for row in self.read("SELECT prev_hash, payload, hash FROM audit_log ORDER BY seq"):
            if row["prev_hash"] != prev or row["hash"] != _digest(prev, row["payload"]):
                return False
            prev = row["hash"]
        return True
