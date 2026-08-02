"""Orquestación del análisis completo por alimentador (F2 + F3/F5 + F4 + F7).

Combina el balance eléctrico (F3/F5) con topología y calidad (F2), flujo de
potencia primario (F4) y score de riesgo de hurto (F7). Cada bloque avanzado es
tolerante a fallos: un error en un módulo no impide entregar el resto.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from ..config import Config, load_config
from ..electrical import formulas as F
from .balance import analyze_feeder


def analyze_feeder_full(tables: dict[str, pd.DataFrame],
                        cfg: Config | None = None) -> tuple[dict[str, pd.DataFrame], set[str]]:
    cfg = cfg or load_config()
    fid = tables["header_meters"]["feeder_id"].iloc[0]
    gold: dict[str, pd.DataFrame] = {}
    stages: set[str] = {"ingest"}

    # --- F3/F5: balance, cargabilidad, PNT ---
    bal = analyze_feeder(tables, cfg)
    gold.update(bal)
    stages |= {"electrical", "balance"}

    segments = tables.get("segments")
    sites = tables.get("sites")
    customers = tables.get("customers")
    consumption = tables.get("consumption")
    header = tables["header_meters"]
    n_months = header.shape[0]
    hours_period = 730.0 * n_months

    # mapa de carga por nodo primario (kW medio) del puesto
    load_map = {}
    if consumption is not None and customers is not None and sites is not None:
        site_energy = consumption.merge(
            customers[["customer_unit_id", "transformer_site_id"]],
            on="customer_unit_id", how="left",
        ).groupby("transformer_site_id")["kwh"].sum()
        node_of = sites.set_index("site_id")["node_id"].to_dict()
        for sid, e in site_energy.items():
            node = node_of.get(sid)
            if node:
                load_map[node] = F.mean_power_kw(float(e), hours_period)

    fg = None
    zones = None
    # --- F2: topología, zonas, calidad ---
    if segments is not None and not segments.empty:
        try:
            from ..topology import (FeederGraph, build_protection_zones,
                                    run_quality_rules)
            fg = FeederGraph.build(fid, segments, sites)
            topo_findings = fg.validate()
            zones, _ = build_protection_zones(fg, tables.get("switching_devices"),
                                              sites, customers)
            q = run_quality_rules(fid, fg, segments, sites,
                                  tables.get("transformer_units"), customers,
                                  tables.get("streetlights"),
                                  tables.get("switching_devices"), zones,
                                  load_map=load_map, cfg=cfg)
            gold["protection_zones"] = zones
            gold["data_quality_findings"] = q
            gold["feeder_topology"] = pd.DataFrame([{
                "feeder_id": fid, "n_nodes": fg.n_nodes, "n_edges": fg.n_edges,
                "n_zones": len(zones), "topo_findings": len(topo_findings),
                "n_quality_findings": len(q),
                "critical_findings": int((q["severity"] == "critica").sum()) if not q.empty else 0,
            }])
            stages.add("topology")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] topología falló: {e}")

    # --- F4: flujo de potencia primario (motor propio) ---
    if fg is not None and load_map:
        try:
            from ..powerflow import network_from_feeder, solve_bfs
            v_ll = float(cfg.electrical["voltage"]["ll_mv"])
            net = network_from_feeder(fg, segments, load_map, v_base_ln=v_ll / (3 ** 0.5))
            res = solve_bfs(net)
            gold["powerflow_results"] = pd.DataFrame([{
                "feeder_id": fid, "primary_loss_kw": round(res.total_loss_kw, 3),
                "v_min_pu": round(res.v_min_pu, 4), "v_max_pu": round(res.v_max_pu, 4),
                "converged": res.converged, "iterations": res.iterations,
                "n_branches": len(net.branches),
            }])
            stages.add("power_flow")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] flujo de potencia falló: {e}")

    # --- F7: score de riesgo (PU + no supervisado + SHAP) ---
    if consumption is not None and customers is not None:
        try:
            from ..ml import train_risk_model
            scores, info = train_risk_model(consumption, customers,
                                            tables.get("theft_labels"), cfg=cfg)
            scores["feeder_id"] = fid
            gold["customer_risk"] = scores          # reemplaza el proxy F0
            stages.add("ml_risk")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] modelo de riesgo falló: {e}")

    return gold, stages
