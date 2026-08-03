"""Adaptador del modelo de datos de CNEL EP (SIGELEC / ArcFM).

Traduce la jerarquía real de CNEL al modelo canónico, resolviendo las relaciones
por ``GLOBALID`` (no por geometría ni por convención de nombres):

    ESTRUCTURA ──┬── PUESTO ── UNIDAD          (p. ej. PuestoTransfDistribucion
                 │                              ── UNIDADTRANSFDISTRIBUCION)
                 └── PUNTO DE CARGA ── CONEXIÓN CONSUMIDOR

El caso del **edificio** es explícito: un ``PuntoCarga`` agrupa N
``CONEXIONCONSUMIDOR`` (medidores). El consumo se mide por conexión, pero la
acometida, la coincidencia y el costo de visita son por punto de carga (§5.3).

Los valores de dominio (fases, configuración de banco) se decodifican con las
tablas de ``config/cnel_mapping.yaml``, verificables contra la GDB real.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from ..config import config_dir
from ..domain.enums import BankConfig, Phase
from ..lakehouse import Lakehouse


def load_cnel_mapping(path: str | Path | None = None) -> dict:
    """Carga el mapeo CNEL (por defecto ``config/cnel_mapping.yaml``)."""
    p = Path(path) if path else config_dir() / "cnel_mapping.yaml"
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Decodificación de dominios
# --------------------------------------------------------------------------

def decode_phase(value, domain: dict) -> str | None:
    """Traduce el dominio 'Phase Designation' de ArcFM a A/B/C/AB/.../ABC.

    Acepta el código numérico (bitmask) o la letra ya escrita.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    # ya viene como letras
    if isinstance(value, str):
        s = value.strip().upper()
        if s in {p.value for p in Phase}:
            return s
        if s.isdigit():
            value = int(s)
        else:
            return None
    try:
        key = int(value)
    except (TypeError, ValueError):
        return None
    # el YAML puede traer las claves como str
    return domain.get(key, domain.get(str(key)))


def decode_bank_config(value, domain: dict, n_units: int | None = None) -> str:
    """Traduce 'Config Lado Baja Banco Transf' a :class:`BankConfig`.

    Si el valor no está en el dominio, **no inventa**: deduce por el número de
    unidades (1→single, 2→open_delta, 3→wye_closed) y lo marca como inferido.
    """
    if isinstance(value, str) and value.strip():
        key = re.sub(r"[^A-Z0-9]", "", value.strip().upper())
        got = domain.get(key)
        if got:
            return got
    if n_units == 1:
        return BankConfig.SINGLE.value
    if n_units == 2:
        return BankConfig.OPEN_DELTA.value
    if n_units == 3:
        return BankConfig.WYE_CLOSED.value
    return BankConfig.INDEPENDENT.value


def decode_tariff(value, domain: dict, default: str = "residential") -> str:
    """Traduce el dominio 'TipoTarifaCIS' a la clase tarifaria canónica.

    Compara en mayúsculas sin separadores y admite variantes por prefijo
    (p. ej. ``RESIDENCIAL-A`` → ``residential``). Si no reconoce el valor
    devuelve ``default`` en vez de inventar una clase.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    key = re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())
    if not key:
        return default
    if key in domain:
        return domain[key]
    # variantes: el valor empieza por una clave conocida (la más larga gana)
    for k in sorted(domain, key=len, reverse=True):
        if key.startswith(k):
            return domain[k]
    return default


def parse_kva(value) -> float | None:
    """Extrae el kVA de un campo que en CNEL viene como texto de dominio."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
    return float(m.group(1).replace(",", ".")) if m else None


# --------------------------------------------------------------------------
# Construcción del modelo canónico
# --------------------------------------------------------------------------

def _rename(df: pd.DataFrame, fields: dict) -> pd.DataFrame:
    """Renombra campos fuente→canónicos; los ausentes se omiten con aviso."""
    out = pd.DataFrame(index=df.index)
    for canonical, source in fields.items():
        if source in df.columns:
            out[canonical] = df[source]
        else:
            logger.debug(f"campo ausente: {source} -> {canonical}")
    return out


def build_canonical(layers: dict[str, pd.DataFrame], mapping: dict,
                    feeder_id: str | None = None) -> dict[str, pd.DataFrame]:
    """Convierte las capas crudas de CNEL al modelo canónico.

    ``layers``: {nombre_de_capa_CNEL: DataFrame}. Devuelve las entidades
    canónicas (poles, sites, transformer_units, load_points, customers, ...).
    """
    dom = mapping.get("domains", {})
    phase_dom = dom.get("phase_designation", {})
    bank_dom = dom.get("bank_config", {})
    lmap = mapping["layers"]
    ff = mapping.get("feeder_field", "ALIMENTADORID")
    out: dict[str, pd.DataFrame] = {}

    def get(entity: str) -> pd.DataFrame | None:
        spec = lmap.get(entity)
        if not spec:
            return None
        raw = layers.get(spec["layer"])
        if raw is None or raw.empty:
            return None
        df = _rename(raw, spec["fields"])
        df["feeder_id"] = (raw[ff].astype(str) if ff in raw.columns
                           else (feeder_id or "UNKNOWN"))
        return df

    # --- poles / estructuras ---
    poles = get("poles")
    if poles is not None:
        out["poles"] = poles

    # --- unidades de transformador (para deducir el banco si falta el dominio) ---
    units = get("transformer_units")
    n_units_by_site: dict[str, int] = {}
    if units is not None:
        units["sn_kva"] = units.get("sn_kva").map(parse_kva) if "sn_kva" in units else None
        if "phase_raw" in units:
            units["phase"] = units["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
            units = units.drop(columns=["phase_raw"])
        units["plate_source"] = "catalog"   # la GDB no trae P0/Pk (Anexo B.4)
        n_units_by_site = units.groupby("site_id").size().to_dict()
        out["transformer_units"] = units

    # --- puestos de transformación ---
    sites = get("sites")
    if sites is not None:
        if "phase_raw" in sites:
            sites["phase"] = sites["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
        raw_cfg = sites["bank_config_raw"] if "bank_config_raw" in sites else None
        sites["bank_config"] = [
            decode_bank_config(raw_cfg.iloc[i] if raw_cfg is not None else None,
                               bank_dom, n_units_by_site.get(sites["site_id"].iloc[i]))
            for i in range(len(sites))
        ]
        sites["kind"] = "transformer"
        if "declared_kva" in sites:
            sites["declared_kva"] = sites["declared_kva"].map(parse_kva)
        sites = sites.drop(columns=[c for c in ("bank_config_raw", "phase_raw")
                                    if c in sites.columns])
        out["sites"] = sites

    # --- punto de carga (el "edificio") ---
    lps = get("load_points")
    if lps is not None:
        if "phase_raw" in lps:
            lps["phase"] = lps["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
            lps = lps.drop(columns=["phase_raw"])
        out["load_points"] = lps

    # --- conexiones consumidor (medidores) ---
    cust = get("customers")
    if cust is not None:
        # El identificador único es CODIGOUNICO. Si falta o viene vacío en
        # algunas filas, se cae a GLOBALID para no perder la conexión: quedarse
        # sin id la haría desaparecer del balance silenciosamente.
        if "customer_unit_id" not in cust.columns:
            cust["customer_unit_id"] = None
        blank = cust["customer_unit_id"].isna() | \
            (cust["customer_unit_id"].astype(str).str.strip() == "")
        if blank.any():
            if "global_id" in cust.columns:
                cust.loc[blank, "customer_unit_id"] = cust.loc[blank, "global_id"]
                logger.warning(
                    f"{int(blank.sum())} conexiones sin CODIGOUNICO: se usa "
                    f"GLOBALID como identificador (revisar calidad del dato).")
            else:
                raise ValueError(
                    "CONEXIONCONSUMIDOR sin CODIGOUNICO ni GLOBALID: no hay "
                    "identificador único para la conexión.")
        if "phase_raw" in cust:
            cust["phase"] = cust["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
            cust = cust.drop(columns=["phase_raw"])
        # heredar del punto de carga: transformador, poste y (si falta) la fase
        if lps is not None:
            lp = lps.set_index("load_point_id")
            cust["transformer_site_id"] = cust["site_id"].map(
                lp["transformer_site_id"]) if "transformer_site_id" in lp else None
            if "pole_id" in lp.columns:
                cust["pole_id"] = cust["site_id"].map(lp["pole_id"])
            if "phase" in lp.columns:
                inherited = cust["site_id"].map(lp["phase"])
                cust["phase"] = cust["phase"].fillna(inherited) if "phase" in cust \
                    else inherited
            if "service_drop_kva" in lp.columns:
                cust["service_drop_kva"] = cust["site_id"].map(lp["service_drop_kva"])
        # --- enriquecer con ATRIBUTOSCONSUMIDOR (CUENTACONTRATO, tarifa, carga) ---
        attrs_spec = lmap.get("customer_attributes")
        attrs_raw = layers.get(attrs_spec["layer"]) if attrs_spec else None
        if attrs_raw is not None and not attrs_raw.empty:
            attrs = _rename(attrs_raw, attrs_spec["fields"])
            attrs = attrs.drop_duplicates(subset=["customer_unit_id"])
            before = len(cust)
            cust = cust.merge(attrs, on="customer_unit_id", how="left",
                              suffixes=("", "_attr"))
            matched = int(cust["cuenta_contrato"].notna().sum()) \
                if "cuenta_contrato" in cust else 0
            logger.info(f"ATRIBUTOSCONSUMIDOR: {matched}/{before} conexiones "
                        f"enlazadas por CODIGOUNICO")
        tdom = dom.get("tariff_class", {})
        tdefault = dom.get("tariff_class_default", "residential")
        if "tariff_raw" in cust.columns:
            cust["tariff_class"] = cust["tariff_raw"].map(
                lambda v: decode_tariff(v, tdom, tdefault))
            cust = cust.drop(columns=["tariff_raw"])
        elif "tariff_class" not in cust.columns:
            cust["tariff_class"] = tdefault
        out["customers"] = cust

    # --- luminarias y dispositivos ---
    for name in ("streetlights", "switching_devices"):
        df = get(name)
        if df is not None:
            if "phase_raw" in df:
                df["phase"] = df["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
                df = df.drop(columns=["phase_raw"])
            out[name] = df

    return out


def site_unit_summary(canonical: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Resumen de la jerarquía puesto→unidad y puntoCarga→conexión.

    Es el informe de ingesta que exige §2.1: cuántas unidades por puesto y
    cuántas conexiones por punto de carga (el caso del edificio).
    """
    rows = []
    units = canonical.get("transformer_units")
    sites = canonical.get("sites")
    if units is not None and sites is not None:
        per_site = units.groupby("site_id").size()
        rows.append({"relacion": "PuestoTransfDistribucion -> UNIDADTRANSFDISTRIBUCION",
                     "padres": int(len(sites)), "hijos": int(len(units)),
                     "hijos_por_padre_max": int(per_site.max()) if len(per_site) else 0,
                     "hijos_por_padre_medio": round(float(per_site.mean()), 2) if len(per_site) else 0.0,
                     "padres_multi": int((per_site > 1).sum())})
    lps = canonical.get("load_points")
    cust = canonical.get("customers")
    if lps is not None and cust is not None:
        per_lp = cust.groupby("site_id").size()
        rows.append({"relacion": "PuntoCarga -> CONEXIONCONSUMIDOR",
                     "padres": int(len(lps)), "hijos": int(len(cust)),
                     "hijos_por_padre_max": int(per_lp.max()) if len(per_lp) else 0,
                     "hijos_por_padre_medio": round(float(per_lp.mean()), 2) if len(per_lp) else 0.0,
                     "padres_multi": int((per_lp > 1).sum())})
    return pd.DataFrame(rows)


def ingest_cnel_fgdb(path: str, root: str, mapping: dict | None = None,
                     extract_date: str | None = None) -> dict:
    """Ingiere una FGDB con el modelo CNEL a BRONZE, ya en modelo canónico."""
    from .fgdb import read_layer

    mapping = mapping or load_cnel_mapping()
    needed = {spec["layer"] for spec in mapping["layers"].values() if "layer" in spec}
    layers: dict[str, pd.DataFrame] = {}
    for name in sorted(needed):
        try:
            layers[name] = read_layer(path, name)
        except Exception as e:
            logger.warning(f"No se pudo leer la capa '{name}': {e}")

    canonical = build_canonical(layers, mapping)
    lake = Lakehouse(root)
    counts: dict[str, int] = {}
    for entity, df in canonical.items():
        if df is None or df.empty:
            continue
        n = 0
        for fid, part in df.groupby("feeder_id"):
            extra = {"extract_date": extract_date} if extract_date else None
            lake.write_partition("bronze", entity, str(fid), part, extra)
            n += len(part)
        counts[entity] = n
    counts["_hierarchy"] = site_unit_summary(canonical).to_dict("records")
    return counts
