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


def write_conductor_catalog(catalogo_estructura: pd.DataFrame,
                            out_path: str | Path | None = None) -> int:
    """Deriva el catálogo de conductores del cliente y lo escribe en
    ``config/conductors_cnel.yaml`` (Anexo D1, ver ``conductor_catalog.py``)."""
    from .conductor_catalog import build_catalog_from_structure_table
    catalog = build_catalog_from_structure_table(catalogo_estructura)
    p = Path(out_path) if out_path else config_dir() / "conductors_cnel.yaml"
    header = (
        "# Catálogo de conductores derivado AUTOMÁTICAMENTE de CATALOGOESTRUCTURA\n"
        "# (DESCRIPCIONLARGA) por `lossan ingest-cnel` — ver\n"
        "# src/lossan/io/conductor_catalog.py. APROXIMADO (física por calibre/\n"
        "# material, sin corrección por trenzado ni GMD real): calibrar contra\n"
        "# el catálogo del fabricante cuando esté disponible (Anexo D1).\n"
        "# No editar a mano — se regenera en cada `ingest-cnel`.\n"
    )
    with p.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump({"conductors": catalog}, fh, allow_unicode=True, sort_keys=True)
    return len(catalog)


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


def _endpoint_id(pt, precision: int = 1) -> str | None:
    if pt is None:
        return None
    return f"{round(pt[0], precision)}_{round(pt[1], precision)}"


def _line_coords(geom):
    """Extrae (primer punto, último punto) de una LineString o MultiLineString."""
    if geom is None or geom.is_empty:
        return None, None
    if geom.geom_type == "MultiLineString":
        parts = list(geom.geoms)
        if not parts:
            return None, None
        return parts[0].coords[0], parts[-1].coords[-1]
    if hasattr(geom, "coords"):
        coords = list(geom.coords)
        if not coords:
            return None, None
        return coords[0], coords[-1]
    return None, None


def _line_endpoints(geoseries) -> tuple[list, list]:
    """node_from/node_to por snapping de coordenadas de los extremos de línea.

    No hay node_from/node_to explícitos en la GDB de CNEL; los tramos que
    comparten un extremo físico (misma coordenada) quedan conectados.
    """
    froms, tos = [], []
    for geom in geoseries:
        a, b = _line_coords(geom)
        froms.append(_endpoint_id(a))
        tos.append(_endpoint_id(b))
    return froms, tos


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
        if "p0_kw" not in units.columns or "pk_kw" not in units.columns:
            from ..config import load_config
            cat = load_config().electrical["transformer_loss_catalog"]
            units["p0_kw"] = units["sn_kva"] * cat["p0_frac_sn"]
            units["pk_kw"] = units["sn_kva"] * cat["pk_frac_sn"]
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

        # SUBTIPO de PuestoTransfDistribucion (verificado por el cliente) es una
        # señal más confiable que CONFIGURACIONLADOBAJA: describe directamente
        # si es integral trifásico o banco de 2/3 unidades. Se usa como fuente
        # primaria cuando está disponible.
        _kind_to_bank = {
            "single": BankConfig.SINGLE.value,
            "integral_3ph": BankConfig.INDEPENDENT.value,   # 1 unidad trifásica, no banco
            "bank2": BankConfig.OPEN_DELTA.value,
            "bank3": BankConfig.WYE_CLOSED.value,
            "biphase": BankConfig.OPEN_WYE_OPEN_DELTA.value,
        }
        n_from_subtype = 0
        if "subtype_raw" in sites.columns:
            subtype_dom = lmap["sites"].get("subtype_domain", {})
            new_cfg = []
            for i in range(len(sites)):
                v = sites["subtype_raw"].iloc[i]
                info = subtype_dom.get(int(v)) if pd.notna(v) else None
                if info is not None:
                    new_cfg.append(_kind_to_bank.get(info["kind"], sites["bank_config"].iloc[i]))
                    n_from_subtype += 1
                else:
                    new_cfg.append(sites["bank_config"].iloc[i])
            sites["bank_config"] = new_cfg
            sites = sites.drop(columns=["subtype_raw"])
            if n_from_subtype:
                logger.info(f"{n_from_subtype} puestos con bank_config resuelto por "
                            f"SUBTIPO (señal más confiable que CONFIGURACIONLADOBAJA).")

        # Reconciliar contra el conteo REAL de unidades (§5.2): un puesto
        # declarado 'wye_closed'/'delta_closed' con != 3 unidades (o
        # 'open_delta'/... con != 2, o 'single' con != 1) es una
        # inconsistencia del dato de placa; el conteo real manda, porque la
        # capacidad se calcula por unidad y una config imposible rompe §13.
        _required_units = {
            BankConfig.SINGLE.value: 1,
            BankConfig.WYE_CLOSED.value: 3, BankConfig.DELTA_CLOSED.value: 3,
            BankConfig.DELTA_4WIRE.value: 3,
            BankConfig.OPEN_DELTA.value: 2, BankConfig.OPEN_WYE_OPEN_DELTA.value: 2,
        }
        _by_count = {1: BankConfig.SINGLE.value, 2: BankConfig.OPEN_DELTA.value,
                     3: BankConfig.WYE_CLOSED.value}
        n_reconciled = 0
        new_cfg = []
        for i, cfg_val in enumerate(sites["bank_config"]):
            n = n_units_by_site.get(sites["site_id"].iloc[i], 0)
            req = _required_units.get(cfg_val)
            if req is not None and req != n:
                new_cfg.append(_by_count.get(n, BankConfig.INDEPENDENT.value))
                n_reconciled += 1
            else:
                new_cfg.append(cfg_val)
        sites["bank_config"] = new_cfg
        if n_reconciled:
            logger.warning(
                f"{n_reconciled} puestos con bank_config declarado inconsistente "
                f"con el número real de unidades: se usó el conteo real.")
        sites["kind"] = "transformer"
        if "declared_kva" in sites:
            sites["declared_kva"] = sites["declared_kva"].map(parse_kva)
        sites = sites.drop(columns=[c for c in ("bank_config_raw", "phase_raw")
                                    if c in sites.columns])
        out["sites"] = sites

        # UNIDADTRANSFDISTRIBUCION no trae ALIMENTADORID propio (no está en
        # la capa): sin esto toda unidad cae en feeder_id=UNKNOWN.
        if units is not None:
            site_feeder = sites.set_index("site_id")["feeder_id"]
            units["feeder_id"] = units["site_id"].map(site_feeder).fillna(units["feeder_id"])
            out["transformer_units"] = units

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
        # heredar del punto de carga: alimentador, transformador, poste y (si
        # falta) la fase. CONEXIONCONSUMIDOR no trae ALIMENTADORID propio
        # (no está en la capa); sin esto todo cliente cae en feeder_id=UNKNOWN.
        if lps is not None:
            lp = lps.set_index("load_point_id")
            if "feeder_id" in lp.columns:
                inherited_feeder = cust["site_id"].map(lp["feeder_id"])
                cust["feeder_id"] = inherited_feeder.fillna(cust["feeder_id"])
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

    # --- tramos (segmentos de red aéreo + subterráneo) ---
    seg_spec = lmap.get("segments")
    if seg_spec:
        frames = []
        for lyr in seg_spec.get("layers", []):
            raw = layers.get(lyr)
            if raw is None or raw.empty:
                continue
            df = _rename(raw, seg_spec["fields"])
            df["feeder_id"] = (raw[ff].astype(str) if ff in raw.columns
                               else (feeder_id or "UNKNOWN"))
            if "phase_raw" in df:
                df["phase"] = df["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
                df = df.drop(columns=["phase_raw"])
            if "length_field" in df:
                df["length_m"] = pd.to_numeric(df["length_field"], errors="coerce")
                df = df.drop(columns=["length_field"])
            geom = getattr(raw, "geometry", None)
            if geom is not None:
                fr, to = _line_endpoints(raw.geometry)
                df["node_from"], df["node_to"] = fr, to
            frames.append(df)
        if frames:
            out["segments"] = pd.concat(frames, ignore_index=True)

    # --- luminarias y dispositivos ---
    for name in ("streetlights", "switching_devices"):
        df = get(name)
        if df is not None:
            if "phase_raw" in df:
                df["phase"] = df["phase_raw"].map(lambda v: decode_phase(v, phase_dom))
                df = df.drop(columns=["phase_raw"])
            if name == "streetlights":
                sl_spec = lmap["streetlights"]
                default_tech = sl_spec.get("technology_default", "led")
                if "technology_raw" in df.columns:
                    tech_dom = sl_spec.get("technology_domain", {})
                    df["technology"] = df["technology_raw"].map(
                        lambda v: tech_dom.get(int(v), default_tech)
                        if pd.notna(v) else default_tech)
                    df = df.drop(columns=["technology_raw"])
                elif "technology" not in df.columns:
                    df["technology"] = default_tech
                # BAJOMEDICION: 1 = tiene medidor propio de AP (su consumo NO
                # se debe estimar por inventario, ya está medido/facturado
                # aparte); 0 o NULL = sin medidor -> se asume no medido.
                if "metered_raw" in df.columns:
                    df["metered"] = df["metered_raw"] == 1
                    df = df.drop(columns=["metered_raw"])
                elif "metered" not in df.columns:
                    df["metered"] = False
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
    for spec in mapping["layers"].values():
        needed.update(spec.get("layers", []))
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

    # --- Catálogo de conductores derivado de CATALOGOESTRUCTURA (Anexo D1) ---
    try:
        cat_estructura = read_layer(path, "CATALOGOESTRUCTURA")
        n_cat = write_conductor_catalog(cat_estructura)
        counts["_conductor_catalog"] = n_cat
    except Exception as e:
        logger.warning(f"No se pudo derivar el catálogo de conductores: {e}")

    return counts
