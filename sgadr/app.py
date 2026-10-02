"""Ensamblado de la aplicación: base de datos + servicios + API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .alerts import AlertService
from .api import Api
from .auth import AuthService
from .service import DemandService
from .store import Store


@dataclass(frozen=True, slots=True)
class App:
    api: Api
    store: Store
    auth: AuthService
    demands: DemandService
    alerts: AlertService


def build_app(db_path: str | Path, *, hsts: bool = False) -> App:
    """Construye el grafo de dependencias con una única instancia de cada servicio."""
    store = Store(db_path)
    auth = AuthService(store)
    demands = DemandService(store)
    alerts = AlertService(store)
    return App(Api(demands, auth, alerts, hsts=hsts), store, auth, demands, alerts)
