"""Catálogos operativos tomados del documento "Circuitos de alerta, demanda y respuesta".

Son datos de referencia, no reglas de negocio: se publican a la interfaz (GET /api/v1/meta)
para ofrecer sugerencias y evitar errores de tipeo. Las ÁREAS sí se validan al asignar una
respuesta, porque la compartimentación depende de que el nombre coincida exactamente con el
área del usuario ejecutor.
"""

from __future__ import annotations

from typing import Final, NamedTuple

# Áreas provinciales que ejecutan respuestas (columna "Área de gobierno" del documento).
AREAS: Final[tuple[str, ...]] = (
    "Protección Civil",
    "Infraestructura",
    "Desarrollo Humano",
    "Salud",
    "Vialidad Provincial",
    "Policía Provincial",
    "APA",
    "SECHEEP",
    "Combustible y fondos",
)


class ResourceType(NamedTuple):
    name: str
    suggested_area: str | None  # None = el documento lo deja "a definir" o es ambiguo


# "Demandas que se pueden recibir" (circuito 4). El área sugerida acelera la asignación del Nodo 00.
RESOURCE_TYPES: Final[tuple[ResourceType, ...]] = (
    ResourceType("Evacuación y rescate (botes, lanchas, anfibios, helicópteros, buzos)", "Protección Civil"),
    ResourceType("Apoyo logístico de Defensa Civil a comités de emergencia locales", "Protección Civil"),
    ResourceType("Centro de evacuados", None),  # Infraestructura o Desarrollo Humano: decide el Nodo 00
    ResourceType("Colchones, frazadas, agua potable, alimentos, pañales y kits de limpieza", "Desarrollo Humano"),
    ResourceType("Medicamentos de urgencia y sueros antiofídicos", "Salud"),
    ResourceType("Refugios temporales de asistencia sanitaria", "Salud"),
    ResourceType("Retroexcavadoras y camiones volcadores", "Vialidad Provincial"),
    ResourceType("Interrupción del tránsito en rutas provinciales", "Policía Provincial"),
    ResourceType("Combustible o fondos para combustible", None),
    ResourceType("Refuerzo de fuerzas de seguridad en zonas evacuadas", "Policía Provincial"),
    ResourceType("Ambulancias de alta complejidad y hospitales regionales", "Salud"),
    ResourceType("Bolsas de arena, nylon, chapa, corte de rancho", "Protección Civil"),
    ResourceType("Bombas de achique de gran caudal", "APA"),
    ResourceType("Máquinas retroexcavadoras, anfibias, oruga", "APA"),
    ResourceType("Grupo electrógeno", "SECHEEP"),
)

# Sugerencias para el campo Municipio (lista del registro ENOS 2026). No se impone: el sistema
# normaliza el nombre para detectar duplicados. Debe validarse contra el listado oficial.
MUNICIPALITIES: Final[tuple[str, ...]] = (
    "Resistencia", "Barranqueras", "Fontana", "Puerto Vilelas", "Puerto Tirol", "Margarita Belén",
    "Colonia Benítez", "Basail", "La Leonesa", "Las Palmas", "Puerto Bermejo", "General Vedia",
    "Isla del Cerrito", "Presidencia Roque Sáenz Peña", "Villa Ángela", "Charata",
    "General San Martín", "Juan José Castelli", "Quitilipi", "Machagai", "Las Breñas",
    "Tres Isletas", "Pampa del Infierno", "Taco Pozo", "Villa Río Bermejito", "El Sauzalito",
    "Miraflores", "Pampa del Indio", "Presidencia Roca", "Campo Largo", "Corzuela",
    "Hermoso Campo", "Gancedo", "General Pinedo", "Santa Sylvina", "Coronel Du Graty",
    "Villa Berthet", "San Bernardo", "Presidencia de la Plaza", "Makallé", "La Escondida",
    "La Verde", "Lapachito", "Laguna Blanca", "Charadai", "Cote Lai", "Colonias Unidas",
    "Ciervo Petiso", "Enrique Urien", "Avia Terai", "Concepción del Bermejo", "Los Frentones",
    "Fuerte Esperanza", "Laguna Limpia", "Capitán Solari", "Samuhú", "Chorotis", "Napenay",
)
