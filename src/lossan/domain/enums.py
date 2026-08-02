"""Enumeraciones del dominio."""
from __future__ import annotations

from enum import Enum


class SiteKind(str, Enum):
    """Tipos de puesto (agrupación funcional en una ubicación, §5.1)."""

    TRANSFORMER = "transformer"      # puesto de transformación
    SWITCHING = "switching"          # puesto de seccionamiento
    METERING = "metering"            # puesto de medida
    CUSTOMER = "customer"            # puesto de cliente
    STREETLIGHT = "streetlight"      # puesto de AP


class UnitKind(str, Enum):
    """Tipos de unidad (equipo individual con placa propia, §5.1)."""

    TRANSFORMER = "transformer"
    SWITCH = "switch"
    METER = "meter"
    LUMINAIRE = "luminaire"
    SERVICE_DROP = "service_drop"    # acometida


class BankConfig(str, Enum):
    """Configuración de banco de transformación (§5.2)."""

    SINGLE = "single"                       # monofásico, 1 unidad
    WYE_CLOSED = "wye_closed"               # estrella cerrada, 3 unidades
    DELTA_CLOSED = "delta_closed"           # delta cerrado, 3 unidades
    OPEN_DELTA = "open_delta"               # delta abierto (V-V), 2 unidades
    OPEN_WYE_OPEN_DELTA = "open_wye_open_delta"  # estrella abierta-delta abierto, 2 unidades
    DELTA_4WIRE = "delta_4wire"             # delta 4 hilos con fase de potencia, 3 desiguales
    INDEPENDENT = "independent"             # unidades independientes (no forman banco)


class Phase(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    AB = "AB"
    BC = "BC"
    CA = "CA"
    ABC = "ABC"


class TariffClass(str, Enum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    STREETLIGHT_LED = "streetlight_led"
    STREETLIGHT_MAGNETIC = "streetlight_magnetic"


class LoadabilityClass(str, Enum):
    OVERLOADED_CRITICAL = "overloaded_critical"
    OVERLOADED = "overloaded"
    HIGH_LOAD = "high_load"
    ADEQUATE = "adequate"
    UNDERUTILIZED = "underutilized"
    VERY_UNDERUTILIZED = "very_underutilized"


class Construction(str, Enum):
    OVERHEAD = "overhead"
    UNDERGROUND = "underground"
