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
                        cfg: Config | None = None,
                        level: str = "full") -> tuple[dict[str, pd.DataFrame], set[str]]:
    """Ejecuta F2+F3/F5+F4+F6+F7 sobre un alimentador.

    Devuelve ``(tablas_gold, fases_completadas)``. Cada bloque avanzado es
    tolerante a fallos: un error en un módulo no impide entregar el resto.
    ``level='n1'`` ejecuta solo topología + balance (tamizaje masivo, §2.4);
    'full' ejecuta además flujo de potencia, estimación de estado y ML.
    """
    cfg = cfg or load_config()
    heavy = level != "n1"
    fid = tables["header_meters"]["feeder_id"].iloc[0]
    hours_month = float(cfg.electrical["hours_per_month"])
    gold: dict[str, pd.DataFrame] = {}
    stages: set[str] = {"ingest"}

    # --- F3/F5: balance, cargabilidad, PNT ---
    # En modo 'full' el modelo ML (F7) reemplaza el proxy de riesgo: no lo calculamos.
    bal = analyze_feeder(tables, cfg, with_risk_proxy=not heavy)
    gold.update(bal)
    stages |= {"electrical", "balance"}

    # --- §14.2: desbalance por puesto (mapeo cliente→fase) ---
    try:
        from .imbalance import compute_site_imbalance
        n_months = tables["header_meters"].shape[0]
        imb = compute_site_imbalance(tables.get("customers"), tables.get("consumption"),
                                     tables.get("sites"), cfg, hours_period=hours_month * n_months)
        if imb is not None and not imb.empty:
            gold["transformer_imbalance"] = imb
    except Exception as e:  # pragma: no cover
        logger.warning(f"[{fid}] desbalance falló: {e}")

    # --- §12: incertidumbre de pérdidas P10/P50/P90 (Monte Carlo) ---
    try:
        from .montecarlo import monte_carlo_table
        b0 = gold["feeder_balance"].iloc[0]
        gold["loss_uncertainty"] = monte_carlo_table(
            fid, float(b0["energy_technical_kwh"]), float(b0["losses_total_kwh"]), cfg)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[{fid}] Monte Carlo falló: {e}")

    # --- §10.3: anomalías de alumbrado público ---
    try:
        from .streetlight import detect_ap_anomalies
        ap = detect_ap_anomalies(tables.get("streetlights"), fid, cfg)
        if ap is not None and not ap.empty:
            gold["streetlight_anomalies"] = ap
    except Exception as e:  # pragma: no cover
        logger.warning(f"[{fid}] anomalías AP falló: {e}")

    segments = tables.get("segments")
    sites = tables.get("sites")
    customers = tables.get("customers")
    consumption = tables.get("consumption")
    header = tables["header_meters"]
    n_months = header.shape[0]
    hours_period = hours_month * n_months

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
    node_to_zone = {}
    # --- F2: topología, zonas, calidad ---
    if segments is not None and not segments.empty:
        try:
            from ..topology import (FeederGraph, build_protection_zones,
                                    run_quality_rules)
            fg = FeederGraph.build(fid, segments, sites, customers,
                                   tables.get('streetlights'))
            topo_findings = fg.validate()
            zones, node_to_zone = build_protection_zones(
                fg, tables.get("switching_devices"), sites, customers)
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
            # §8.3: índice de confiabilidad del modelo 0-100
            from .reliability import reliability_table
            b0 = gold["feeder_balance"].iloc[0]
            # penaliza por incoherencias del balance (antes usaba una métrica nula)
            incoherence = 0.0 if b0["balance_coherent"] else 1.0
            gold["reliability_index"] = reliability_table(fid, q, fg.n_edges, incoherence)
            stages.add("topology")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] topología falló: {e}")

    # --- F4: flujo de potencia primario (motor propio) ---
    if heavy and fg is not None and load_map:
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

    # --- F6: estimación de estado / ramales sin medición (§14.3) ---
    if heavy and fg is not None and consumption is not None and customers is not None and sites is not None:
        try:
            from ..stateest import pseudo_measurements, reconcile_by_zone, run_wls
            merged = consumption.merge(
                customers[["customer_unit_id", "transformer_site_id"]],
                on="customer_unit_id", how="left")
            monthly = (merged.groupby(["transformer_site_id", "year_month"])["kwh"]
                       .sum().reset_index())
            stats = monthly.groupby("transformer_site_id")["kwh"].agg(["mean", "std"]).fillna(0.0)
            stats["mean_kw"] = stats["mean"] / hours_month
            stats["std_kw"] = stats["std"] / hours_month
            stats = stats.reset_index().rename(columns={"transformer_site_id": "site_id"})
            bal = gold["feeder_balance"].iloc[0]
            measured_total_kw = max(
                0.0, (bal["energy_header_kwh"] - bal["energy_technical_kwh"]) / hours_period)
            ids, z, sigma = pseudo_measurements(stats)
            res = run_wls(z, sigma, measured_total_kw)
            node_of = sites.set_index("site_id")["node_id"].to_dict()
            site_to_zone = {sid: node_to_zone.get(node_of.get(sid, ""), "HEAD") for sid in ids}
            zone_se = reconcile_by_zone(ids, res.correction, res.normalized_residuals,
                                        site_to_zone, fid)
            zone_se["gross_error"] = bool(res.gross_error)
            zone_se["chi2"] = round(res.chi2, 2)
            gold["zone_state_estimation"] = zone_se
            stages.add("state_estimation")

            # Verificación independiente del balance (§22.3): la carga no
            # contabilizada que estima el WLS (ponderando por incertidumbre) debe
            # coincidir con la PNT contable una vez descontados AP y ENS. Es un
            # camino distinto al de la resta, por lo que su discrepancia SÍ mide
            # consistencia (a diferencia de recomputar la propia identidad).
            unaccounted_kwh = float(zone_se["unaccounted_load_kw"].sum()) * hours_period
            pnt_independent = unaccounted_kwh - float(bal["energy_streetlight_kwh"]) \
                - float(bal["energy_ens_kwh"])
            hdr = float(bal["energy_header_kwh"])
            disc = abs(pnt_independent - float(bal["pnt_kwh"])) / hdr * 100.0 if hdr else None
            b = gold["feeder_balance"].copy()
            b.loc[b.index[0], "pnt_independent_kwh"] = round(pnt_independent, 1)
            b.loc[b.index[0], "unexplained_pct"] = round(disc, 4) if disc is not None else None
            gold["feeder_balance"] = b
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] estimación de estado falló: {e}")

    # --- F7: score de riesgo (PU + no supervisado + SHAP) ---
    if heavy and consumption is not None and customers is not None:
        try:
            from ..ml import train_risk_model
            scores, info = train_risk_model(consumption, customers,
                                            tables.get("theft_labels"), cfg=cfg)
            scores["feeder_id"] = fid
            gold["customer_risk"] = scores          # reemplaza el proxy F0
            stages.add("ml_risk")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] modelo de riesgo falló: {e}")

        # --- §9.4: curvas de carga por clustering ---
        try:
            from ..ml.load_curves import cluster_load_profiles
            assign, cent = cluster_load_profiles(consumption, customers)
            assign["feeder_id"] = fid
            cent["feeder_id"] = fid
            gold["load_clusters"] = assign
            gold["load_curve_centroids"] = cent
        except Exception as e:  # pragma: no cover
            logger.warning(f"[{fid}] curvas de carga falló: {e}")

    return gold, stages
