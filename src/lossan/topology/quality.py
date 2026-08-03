"""Módulo M2 — reglas determinísticas de calidad de datos R01-R25 (§8.1).

Motor de reglas activables y parametrizables por ``config/rules.yaml``. Cada
hallazgo lleva ``rule_id, element_id, severity, evidence, confidence``.
"""
from __future__ import annotations

import math

import pandas as pd

from ..config import Config, load_config

SQRT3 = math.sqrt(3.0)


def run_quality_rules(
    feeder_id: str,
    fg,                                  # FeederGraph
    segments: pd.DataFrame,
    sites: pd.DataFrame | None = None,
    units: pd.DataFrame | None = None,
    customers: pd.DataFrame | None = None,
    streetlights: pd.DataFrame | None = None,
    devices: pd.DataFrame | None = None,
    zones: pd.DataFrame | None = None,
    load_map: dict[str, float] | None = None,
    cfg: Config | None = None,
) -> pd.DataFrame:
    """Ejecuta las reglas R01-R25 sobre un alimentador y devuelve los hallazgos.

    Cada hallazgo lleva ``rule_id, element_id, severity, evidence, confidence`` y
    el ``suggested_value`` cuando aplica. Las reglas se activan/parametrizan por
    ``config/rules.yaml``.
    """
    cfg = cfg or load_config()
    R = cfg.rules
    findings: list[dict] = []

    def emit(rid, element_id, evidence, confidence=1.0, suggested=None):
        meta = R.get(rid, {})
        if not meta.get("enabled", False):
            return
        findings.append({
            "feeder_id": feeder_id, "rule_id": rid, "element_id": element_id,
            "severity": meta.get("severity", "media"), "evidence": evidence,
            "confidence": round(confidence, 3), "suggested_value": suggested,
        })

    prim = segments[segments["section"] == "primary"]
    # índices para vecindad topológica
    by_node_to = {r.node_to: r for r in segments.itertuples()}
    children: dict[str, list] = {}
    for r in segments.itertuples():
        children.setdefault(r.node_from, []).append(r)

    def upstream_seg(seg):
        return by_node_to.get(seg.node_from)

    # ---- R01 conductor sándwich ----
    for r in prim.itertuples():
        up = upstream_seg(r)
        kids = [c for c in children.get(r.node_to, []) if c.section == "primary"]
        if up is not None and up.section == "primary" and kids:
            up_c = up.conductor_code
            down_cs = {c.conductor_code for c in kids}
            if len(down_cs) == 1 and up_c in down_cs and r.conductor_code != up_c:
                emit("R01", r.segment_id,
                     f"Conductor {r.conductor_code} entre tramos {up_c} iguales",
                     confidence=0.9, suggested=up_c)

    # ---- R02 cambio de conductor en tramo muy corto ----
    min_len = R.get("R02", {}).get("min_length_m", 15)
    for r in prim.itertuples():
        up = upstream_seg(r)
        if up is not None and r.length_m < min_len and r.conductor_code != up.conductor_code:
            emit("R02", r.segment_id,
                 f"Tramo de {r.length_m} m con cambio de conductor", confidence=0.8)

    # ---- R03 no monotonicidad de calibre (sección creciente lejos de fuente) ----
    order = {c: i for i, c in enumerate(cfg.conductor_ordering["primary"])}
    for r in prim.itertuples():
        up = upstream_seg(r)
        if up is not None and r.conductor_code in order and up.conductor_code in order:
            if order[r.conductor_code] > order[up.conductor_code]:
                emit("R03", r.segment_id,
                     f"Calibre creciente {up.conductor_code}->{r.conductor_code} alejándose de la fuente",
                     confidence=0.6)

    # ---- R04 cambio de material Al<->Cu ----
    for r in segments.itertuples():
        up = upstream_seg(r)
        if up is not None and getattr(r, "material", None) and getattr(up, "material", None):
            if r.material != up.material:
                emit("R04", r.segment_id, f"Cambio de material {up.material}->{r.material}",
                     confidence=0.5)

    # ---- R06 discontinuidad de fases (hijo no contenido en padre) ----
    for r in segments.itertuples():
        up = upstream_seg(r)
        if up is not None:
            if not set(str(r.phase)) <= set(str(up.phase)):
                emit("R06", r.segment_id,
                     f"Fases {r.phase} no contenidas en el padre {up.phase}", confidence=0.85)

    # ---- R07 discontinuidad de tensión sin transformador ----
    for r in segments.itertuples():
        up = upstream_seg(r)
        if up is not None and up.voltage_ll and r.voltage_ll:
            if abs(up.voltage_ll - r.voltage_ll) / max(up.voltage_ll, r.voltage_ll) > 0.05:
                emit("R07", r.segment_id,
                     f"Salto de tensión {up.voltage_ll}->{r.voltage_ll} V sin transformador",
                     confidence=0.9)

    # ---- R08 feeder_id inconsistente con la traza ----
    for r in segments.itertuples():
        decl = getattr(r, "feeder_id_declared", feeder_id)
        if decl and decl != feeder_id:
            emit("R08", r.segment_id,
                 f"feeder_id declarado {decl} != traza {feeder_id}", confidence=1.0,
                 suggested=feeder_id)

    # ---- R09 ampacidad insuficiente ----
    if load_map:
        for r in segments.itertuples():
            load = fg.subtree_load(r.node_to, load_map)["load_kva"] if r.node_to in fg.idx else 0.0
            if load > 0 and r.voltage_ll:
                i = load * 1000.0 / (SQRT3 * r.voltage_ll) if str(r.phase) == "ABC" \
                    else load * 1000.0 / r.voltage_ll
                if i > r.ampacity_a:
                    emit("R09", r.segment_id,
                         f"Corriente {i:.0f} A > ampacidad {r.ampacity_a} A", confidence=0.8)

    # ---- R10 conductor de secundario en tramo primario o viceversa ----
    for r in segments.itertuples():
        sec = getattr(r, "section", None)
        v = r.voltage_ll or 0
        if sec == "secondary" and v > 1000:
            emit("R10", r.segment_id, "Conductor secundario en tramo de tensión primaria")
        if sec == "primary" and 0 < v < 1000:
            emit("R10", r.segment_id, "Conductor primario en tramo de baja tensión")

    # ---- R13 transformador con nodo aguas arriba no primario ----
    if sites is not None:
        seg_v = {r.node_to: r.voltage_ll for r in segments.itertuples()}
        for s in sites.itertuples():
            nid = getattr(s, "node_id", None)
            if nid is not None:
                v_up = seg_v.get(nid)
                if v_up is not None and v_up < 1000:
                    emit("R13", s.site_id,
                         f"Transformador en nodo de {v_up} V (no primario)", confidence=0.9)

    # ---- R15 cliente en puesto distinto al de la traza ----
    if customers is not None:
        for c in customers.itertuples():
            traced = None
            up = fg.parent.get(c.customer_unit_id)
            if up and up.endswith("_S"):
                traced = up[:-2]  # nodo primario del puesto
            # (comparación declarativa simplificada; discrepancia geográfica en F6)
            # Aquí sólo marcamos clientes sin traza a un puesto.
            if traced is None and c.customer_unit_id in fg.idx:
                emit("R15", c.customer_unit_id,
                     "Cliente sin puesto de transformación por traza", confidence=0.5)

    # ---- R20 dispositivo sin estado normal ----
    if devices is not None:
        for d in devices.itertuples():
            if not getattr(d, "normal_state", None) or str(d.normal_state) not in ("NA", "NC"):
                emit("R20", d.device_id, "Dispositivo de maniobra sin estado normal definido")

    # ---- R22 transformador/cliente no alcanzable ----
    reachable = set(fg.trace_downstream(fg.source)) | {fg.source}
    if sites is not None:
        for s in sites.itertuples():
            nid = getattr(s, "node_id", None)
            if nid is not None and nid not in reachable:
                emit("R22", s.site_id, "Puesto no alcanzable desde la fuente")
    if customers is not None:
        unreachable = [c.customer_unit_id for c in customers.itertuples()
                       if c.customer_unit_id in fg.idx and c.customer_unit_id not in reachable]
        for cu in unreachable[:100]:
            emit("R22", cu, "Cliente no alcanzable desde la fuente")

    # ---- R23 zona sin dispositivo aguas arriba ----
    if zones is not None:
        for z in zones.itertuples():
            if z.zone_id != "HEAD" and not getattr(z, "has_upstream_device", True):
                emit("R23", z.zone_id, "Zona de protección sin dispositivo aguas arriba")

    # ---- R25 luminaria sin puesto de transformación asignable ----
    if streetlights is not None:
        for l in streetlights.itertuples():
            if not getattr(l, "transformer_site_id", None):
                emit("R25", l.streetlight_id, "Luminaria sin puesto de transformación por traza")

    cols = ["feeder_id", "rule_id", "element_id", "severity", "evidence",
            "confidence", "suggested_value"]
    return pd.DataFrame(findings, columns=cols)
