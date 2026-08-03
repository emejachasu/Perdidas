"""Modelo canónico con pydantic (§4, §5).

Toda entidad lleva feeder_id declarado y por traza, site_id, pole_id,
fechas y banderas de calidad. Estas clases documentan y validan el esquema;
el procesamiento masivo opera sobre Parquet/DuckDB con este mismo esquema.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from .enums import (
    BankConfig,
    Construction,
    Phase,
    SiteKind,
    TariffClass,
    UnitKind,
)


class Base(BaseModel):
    feeder_id_declared: str = Field(..., description="feeder_id declarado en el SIG")
    feeder_id_traced: str | None = Field(None, description="feeder_id por traza topológica")
    created_date: date | None = None
    run_id: str | None = None
    quality_flags: list[str] = Field(default_factory=list)


class Pole(Base):
    """Poste — activo físico de soporte (1,6 M). Unidad de intervención (§5.4)."""

    pole_id: str
    x: float
    y: float
    pole_type: str | None = None
    height_m: float | None = None


class Site(Base):
    """Puesto — agrupación funcional en una ubicación (§5.1)."""

    site_id: str
    pole_id: str | None = None
    kind: SiteKind
    bank_config: BankConfig | None = None   # solo puestos de transformación
    node_id: str | None = None


class TransformerUnitModel(Base):
    """Unidad de transformador con placa propia (§5.1-5.2)."""

    unit_id: str
    site_id: str
    kind: UnitKind = UnitKind.TRANSFORMER
    sn_kva: float
    p0_kw: float          # pérdidas de vacío (placa o catálogo)
    pk_kw: float          # pérdidas de carga nominal
    z_pct: float | None = None
    voltage_ln: float | None = None
    phase: Phase | None = None
    serial: str | None = None
    plate_source: str = "catalog"   # 'plate' | 'catalog' (marcado del origen)


class LoadPoint(Base):
    """Punto de carga — el "puesto de cliente" del modelo CNEL (`PuntoCarga`).

    Es la **acometida física**: un edificio o predio tiene UN punto de carga y
    puede colgar de él VARIAS conexiones consumidor (medidores). El balance con
    sentido físico y el costo de una visita son a este nivel (§5.3, §17.1).
    """

    load_point_id: str
    transformer_site_id: str | None = None   # puesto de transformación que lo alimenta
    pole_id: str | None = None               # estructura de soporte
    phase: Phase | None = None
    service_drop_kva: float | None = None    # capacidad de la acometida compartida
    reading_route: str | None = None
    reading_sequence: str | None = None
    x: float | None = None
    y: float | None = None


class Customer(Base):
    """Unidad de servicio = medidor (`CONEXIONCONSUMIDOR` en CNEL).

    Varias comparten un mismo punto de carga (§5.3): en un edificio hay 1 punto
    de carga y N conexiones consumidor. ``site_id`` apunta a ese punto de carga.
    """

    customer_unit_id: str
    site_id: str          # punto de carga (PuntoCarga) al que pertenece
    pole_id: str | None = None
    tariff_class: TariffClass
    phase: Phase | None = None
    installed_load_kw: float | None = None
    service_drop_kva: float | None = None
    transformer_site_id: str | None = None   # por traza (heredado del punto de carga)
    customer_code: str | None = None         # código comercial (cruce con consumo)
    meter_serial: str | None = None
    meter_type: str | None = None


class ConsumptionRecord(BaseModel):
    customer_unit_id: str
    feeder_id: str
    year_month: str       # 'YYYY-MM' — clave de partición junto con feeder_id
    kwh: float
    kvarh: float | None = None
    estimated: bool = False   # lectura estimada (marcado, no imputación silenciosa)


class Segment(Base):
    """Tramo / vano."""

    segment_id: str
    node_from: str
    node_to: str
    length_m: float
    conductor_code: str
    r_ohm_per_km: float
    x_ohm_per_km: float
    ampacity_a: float
    phase: Phase
    voltage_ll: float
    construction: Construction


class Streetlight(Base):
    """Luminaria (unidad de AP)."""

    streetlight_id: str
    site_id: str | None = None
    transformer_site_id: str | None = None
    technology: str = "led"
    lamp_w: float = 100.0
    tariff_class: TariffClass = TariffClass.STREETLIGHT_LED


class HeaderMeter(BaseModel):
    """Medidor de cabecera del alimentador."""

    feeder_id: str
    year_month: str
    kwh: float
    kvarh: float | None = None


class SwitchingDevice(Base):
    """Dispositivo de maniobra (§7.1)."""

    device_id: str
    site_id: str | None = None
    node_id: str
    type: str                         # seccionador, reconectador, interruptor, fusible...
    normal_state: str                 # NA / NC
    current_state: str | None = None
    remote: bool = False


class SwitchingEvent(BaseModel):
    """Evento de conmutación desde SCADA/DMS/ADMS (§7.2)."""

    device_id: str
    timestamp: str
    estado_previo: str
    estado_nuevo: str
    motivo: str | None = None         # maniobra / falla / transferencia
    operador: str | None = None


class ProtectionZone(BaseModel):
    """Zona de protección — definición operativa de ramal (§7.5)."""

    feeder_id: str
    zone_id: str
    parent_zone: str | None = None
    n_customers: int = 0
    n_tx_sites: int = 0


class FieldInspection(BaseModel):
    """§23.1 — captura de resultados de campo. Definido desde F0 aunque vacío.

    Sin esto el modelo NUNCA mejora y la reserva de exploración pierde sentido.
    """

    inspection_id: str
    site_id: str
    pole_id: str | None = None
    customer_unit_id: str | None = None
    inspected_date: date
    finding: bool                        # hallazgo sí/no
    finding_type: str | None = None
    recovered_kwh: float | None = None
    actual_cost_usd: float | None = None
    crew_id: str | None = None
    source: str = "directed"             # 'directed' | 'exploration'
    photo_uris: list[str] = Field(default_factory=list)


CANONICAL_MODELS = {
    "poles": Pole,
    "sites": Site,
    "transformer_units": TransformerUnitModel,
    "load_points": LoadPoint,
    "customers": Customer,
    "consumption": ConsumptionRecord,
    "segments": Segment,
    "streetlights": Streetlight,
    "header_meters": HeaderMeter,
    "switching_devices": SwitchingDevice,
    "switching_events": SwitchingEvent,
    "protection_zones": ProtectionZone,
    "field_inspections": FieldInspection,
}
