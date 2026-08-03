"""Dashboard web profesional por alimentador (§18).

Muestra el avance del pipeline por alimentador y permite ir viendo el detalle
analítico de cada uno: balance de energía, PNT vs. pérdidas técnicas,
cargabilidad de puestos y ranking de riesgo.

Ejecutar:  lossan dashboard    (o)   streamlit run src/lossan/dashboard/app.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Permitir ejecución directa vía `streamlit run`.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lossan.lakehouse import Lakehouse  # noqa: E402

# --- Paleta / tema ---
PALETTE = {
    "bg": "#0e1117", "panel": "#161b26", "accent": "#4c8bf5",
    "technical": "#3b82f6", "pnt": "#ef4444", "billed": "#22c55e",
    "streetlight": "#f59e0b", "ok": "#22c55e", "warn": "#f59e0b", "bad": "#ef4444",
}
CLASS_COLORS = {
    "overloaded_critical": "#b91c1c", "overloaded": "#ef4444",
    "high_load": "#f59e0b", "adequate": "#22c55e",
    "underutilized": "#38bdf8", "very_underutilized": "#818cf8",
}

st.set_page_config(page_title="Pérdidas · Avance por alimentador",
                   page_icon="⚡", layout="wide")


def _root() -> str:
    return os.environ.get("LOSSAN_LAKEHOUSE", str(Path.cwd() / "data" / "lake"))


@st.cache_data(show_spinner=False)
def load_gold(root: str) -> dict[str, pd.DataFrame]:
    lake = Lakehouse(root)
    return {
        "status": lake.read_entity("gold", "feeder_status"),
        "balance": lake.read_entity("gold", "feeder_balance"),
        "loadability": lake.read_entity("gold", "transformer_loadability"),
        "risk": lake.read_entity("gold", "customer_risk"),
        "quality": lake.read_entity("gold", "data_quality_findings"),
        "zones": lake.read_entity("gold", "protection_zones"),
        "topology": lake.read_entity("gold", "feeder_topology"),
        "powerflow": lake.read_entity("gold", "powerflow_results"),
        "transfers": lake.read_entity("gold", "feeder_transfers"),
        "state_est": lake.read_entity("gold", "zone_state_estimation"),
        "plan": lake.read_entity("gold", "inspection_plan"),
        "summary": lake.read_entity("gold", "campaign_summary"),
        "curve": lake.read_entity("gold", "allocation_curve"),
        "rank_sites": lake.read_entity("gold", "ranking_sites"),
        "recon_causes": lake.read_entity("gold", "pq_reconciliation_causes"),
        "imbalance": lake.read_entity("gold", "transformer_imbalance"),
        "uncertainty": lake.read_entity("gold", "loss_uncertainty"),
        "reliability": lake.read_entity("gold", "reliability_index"),
        "ap_anomalies": lake.read_entity("gold", "streetlight_anomalies"),
    }


def _metric_card(col, label, value, help_text=""):
    col.metric(label, value, help=help_text)


def _filt(df, fid):
    if df is None or df.empty or "feeder_id" not in df.columns:
        return df if df is not None else pd.DataFrame()
    return df[df["feeder_id"] == fid]


def main() -> None:
    st.markdown(
        "<h1 style='margin-bottom:0'>⚡ Plataforma de Pérdidas — Avance por Alimentador</h1>"
        "<p style='color:#94a3b8;margin-top:4px'>Análisis técnico vs. no técnico · "
        "topología · flujo de potencia · calidad de datos · riesgo de hurto (PU+SHAP)</p>",
        unsafe_allow_html=True,
    )

    root = _root()
    data = load_gold(root)
    status, balance = data["status"], data["balance"]

    if status.empty or balance.empty:
        st.warning(
            f"No hay resultados en GOLD ({root}).\n\n"
            "Genera y procesa el universo:\n\n"
            "```\nlossan generate\nlossan run\n```"
        )
        return

    # ============ VISTA GLOBAL ============
    st.subheader("Resumen global")
    tot_header = balance["energy_header_kwh"].sum()
    tot_pnt = balance["pnt_kwh"].sum()
    tot_tech = balance["energy_technical_kwh"].sum()
    c = st.columns(5)
    _metric_card(c[0], "Alimentadores", f"{len(status)}")
    _metric_card(c[1], "Avance medio", f"{status['progress_pct'].mean():.0f}%")
    _metric_card(c[2], "Balance cerrado", f"{int(status['balance_closed'].sum())}/{len(status)}",
                 "Residuo < 0,5% y PNT ≥ 0 (§22.3)")
    _metric_card(c[3], "PNT global", f"{100*tot_pnt/tot_header:.1f}%",
                 "Pérdidas no técnicas sobre energía de cabecera")
    _metric_card(c[4], "Técnicas global", f"{100*tot_tech/tot_header:.1f}%")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Avance del pipeline por alimentador**")
        s = status.sort_values("feeder_id").copy()
        s["estado"] = s["balance_closed"].map({True: "Balance cerrado", False: "Requiere revisión"})
        fig = px.bar(s, x="feeder_id", y="progress_pct", color="estado",
                     color_discrete_map={"Balance cerrado": PALETTE["ok"],
                                         "Requiere revisión": PALETTE["warn"]},
                     labels={"progress_pct": "Avance (%)", "feeder_id": "Alimentador"})
        fig.update_layout(height=340, template="plotly_dark", legend_title="",
                          margin=dict(l=10, r=10, t=10, b=10))
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("**PNT vs. Pérdidas técnicas (% cabecera)**")
        b = balance.sort_values("feeder_id")
        fig2 = go.Figure()
        fig2.add_bar(x=b["feeder_id"], y=b["technical_pct"], name="Técnicas",
                     marker_color=PALETTE["technical"])
        fig2.add_bar(x=b["feeder_id"], y=b["pnt_pct"], name="PNT",
                     marker_color=PALETTE["pnt"])
        fig2.update_layout(barmode="stack", height=340, template="plotly_dark",
                           margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**Tabla de avance**")
    show = status.sort_values("pnt_pct", ascending=False)[
        ["feeder_id", "progress_pct", "stages_done", "stages_total",
         "balance_closed", "pnt_pct", "technical_pct", "n_customers", "n_tx_sites", "runtime_s"]
    ]
    st.dataframe(show, use_container_width=True, hide_index=True,
                 column_config={"progress_pct": st.column_config.ProgressColumn(
                     "Avance", min_value=0, max_value=100, format="%.0f%%")})

    # ============ PLAN DE CAMPAÑA (F8, nivel sistema) ============
    summary = data["summary"]
    if not summary.empty:
        st.divider()
        st.subheader("Plan de campaña — priorización con presupuesto de campo (§17)")
        s = summary.iloc[0]
        cc = st.columns(5)
        _metric_card(cc[0], "Presupuesto", f"${s['budget_field_usd']/1e6:.1f} M",
                     "Exclusivo de campo (§17)")
        _metric_card(cc[1], "Puestos seleccionados", f"{int(s['sites_selected'])}")
        _metric_card(cc[2], "Visitas totales", f"{int(s['visits_total'])}",
                     "Dirigidas + reserva de exploración")
        _metric_card(cc[3], "Beneficio esperado", f"${s['expected_benefit_usd']/1e6:.2f} M")
        _metric_card(cc[4], "ROI campaña", f"{s['roi_campaign']:.1f}×")
        pcols = [c for c in summary.columns if c.startswith("precision@")]
        if pcols:
            st.caption("Precision@k con k derivado del presupuesto (§17.2): " +
                       " · ".join(f"{c.split('(')[0]}={s[c]:.2f}" for c in pcols))
        g1, g2 = st.columns([3, 2])
        with g1:
            curve = data["curve"]
            if not curve.empty:
                st.markdown("**Curva de asignación óptima (energía recuperable vs presupuesto)**")
                figc = px.line(curve, x="budget_usd", y="recoverable_kwh_month", markers=True)
                figc.add_vline(x=float(s["budget_field_usd"]), line_dash="dash",
                               line_color=PALETTE["accent"])
                figc.update_layout(height=300, template="plotly_dark",
                                   margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(figc, use_container_width=True)
        with g2:
            rk = data["rank_sites"]
            if not rk.empty:
                st.markdown("**Top puestos por ROI**")
                st.dataframe(rk[["site_id", "feeder_id", "n_units", "benefit_usd",
                                 "cost_usd", "roi"]].head(15),
                             use_container_width=True, hide_index=True, height=300)

    # ============ DRILL-DOWN POR ALIMENTADOR ============
    st.divider()
    st.subheader("Detalle por alimentador")
    fid = st.selectbox("Selecciona un alimentador", sorted(status["feeder_id"].unique()))

    bal = balance[balance["feeder_id"] == fid].iloc[0]
    load = data["loadability"]
    load = load[load["feeder_id"] == fid] if not load.empty else load
    risk = data["risk"]
    risk = risk[risk["feeder_id"] == fid] if not risk.empty else risk

    k = st.columns(4)
    _metric_card(k[0], "Energía cabecera", f"{bal['energy_header_kwh']/1e6:.2f} GWh")
    _metric_card(k[1], "PNT", f"{bal['pnt_pct']:.1f}%",
                 f"{bal['pnt_kwh']/1e3:.0f} MWh")
    _metric_card(k[2], "Técnicas", f"{bal['technical_pct']:.1f}%")
    _metric_card(k[3], "Residuo balance", f"{bal['residual_pct']:.3f}%",
                 "Objetivo < 0,5% (§22.3)")
    rel = _filt(data["reliability"], fid)
    if not rel.empty:
        ri = rel.iloc[0]["reliability_index"]
        color = "🟢" if ri >= 70 else ("🟡" if ri >= 40 else "🔴")
        st.caption(f"{color} Índice de confiabilidad del modelo (§8.3): **{ri:.0f}/100** "
                   f"— penaliza la priorización donde el problema es de datos, no de hurto.")
    unc = _filt(data["uncertainty"], fid)
    if not unc.empty:
        u = unc.iloc[0]
        st.caption(f"Incertidumbre Monte Carlo (§12) — PNT P10/P50/P90: "
                   f"{u['pnt_p10']/1e3:.0f} / {u['pnt_p50']/1e3:.0f} / {u['pnt_p90']/1e3:.0f} MWh · "
                   f"Técnicas P10/P90: {u['technical_p10']/1e3:.0f} / {u['technical_p90']/1e3:.0f} MWh")
    if bal["pnt_negative_alert"]:
        st.error("⚠️ PNT < 0: error inequívoco de balance (§13). Primera hipótesis: "
                 "transferencia entre alimentadores no registrada.")

    quality = _filt(data["quality"], fid)
    zones = _filt(data["zones"], fid)
    topo = _filt(data["topology"], fid)
    pf = _filt(data["powerflow"], fid)

    tab_bal, tab_topo, tab_pf, tab_risk, tab_plan = st.tabs(
        ["⚖️ Balance & Cargabilidad", "🕸️ Topología & Calidad",
         "🔌 Flujo de potencia", "🎯 Riesgo de hurto", "🗺️ Estado & Plan"])

    with tab_bal:
        d1, d2 = st.columns(2)
        with d1:
            st.markdown("**Descomposición del balance de energía (§13)**")
            waterfall = go.Figure(go.Waterfall(
                orientation="v",
                measure=["absolute", "relative", "relative", "relative", "relative"],
                x=["Cabecera", "− Facturada", "− Alumbrado público", "− Técnicas", "= PNT"],
                y=[bal["energy_header_kwh"], -bal["energy_billed_kwh"],
                   -bal["energy_streetlight_kwh"], -bal["energy_technical_kwh"], 0],
                connector={"line": {"color": "#475569"}}))
            waterfall.update_layout(height=360, template="plotly_dark",
                                    margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(waterfall, use_container_width=True)
        with d2:
            st.markdown("**Clasificación de cargabilidad de puestos (§14.1)**")
            if not load.empty:
                counts = load["loadability_class"].value_counts().reset_index()
                counts.columns = ["clase", "n"]
                fig3 = px.bar(counts, x="n", y="clase", orientation="h", color="clase",
                              color_discrete_map=CLASS_COLORS)
                fig3.update_layout(height=360, template="plotly_dark", showlegend=False,
                                   margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig3, use_container_width=True)
        st.markdown("**Puestos de transformación (cargabilidad por configuración de banco)**")
        if not load.empty:
            st.dataframe(
                load[["site_id", "bank_config", "n_units", "capacity_kva", "s_max_kva",
                      "loadability", "loadability_class", "bank_quality_flags"]]
                .sort_values("loadability", ascending=False),
                use_container_width=True, hide_index=True, height=300)
        imb = _filt(data["imbalance"], fid)
        if not imb.empty:
            st.markdown("**Desbalance por puesto (§14.2) — corriente de neutro y rebalanceo**")
            ic = st.columns(3)
            ic[0].metric("Puestos desbalanceados", f"{int(imb['flagged'].sum())}/{len(imb)}",
                         "> umbral configurado")
            ic[1].metric("Desbalance medio", f"{imb['imbalance_pct'].mean():.0f}%")
            ic[2].metric("Beneficio rebalanceo", f"{imb['rebalance_benefit_kwh'].sum()/1e3:.1f} MWh",
                         "energía recuperable al balancear")
            st.dataframe(imb.sort_values("imbalance_pct", ascending=False)
                         [["site_id", "i_a", "i_b", "i_c", "i_neutral", "imbalance_pct",
                           "rebalance_benefit_kwh"]].head(15),
                         use_container_width=True, hide_index=True, height=240)
        rc = _filt(data["recon_causes"], fid)
        if not rc.empty:
            st.markdown("**Reconciliación de P y Q — impacto del cálculo actual por causa (§9.3)**")
            figr = px.bar(rc, x="pct", y="cause", orientation="h", color="unit",
                          hover_data=["corrected", "current", "delta"],
                          labels={"pct": "desviación del cálculo actual (%)", "cause": ""})
            figr.update_layout(height=260, template="plotly_dark",
                               margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(figr, use_container_width=True)
            st.caption("Diferencia del cálculo actual (presunto erróneo, §9.1) vs. el "
                       "corregido (§9.2): coincidencia, energía-vs-demanda, cosφ y factor √3.")

    with tab_topo:
        if not topo.empty:
            tr = topo.iloc[0]
            tcols = st.columns(5)
            _metric_card(tcols[0], "Nodos", f"{int(tr['n_nodes'])}")
            _metric_card(tcols[1], "Tramos", f"{int(tr['n_edges'])}")
            _metric_card(tcols[2], "Zonas de protección", f"{int(tr['n_zones'])}")
            _metric_card(tcols[3], "Hallazgos de calidad", f"{int(tr['n_quality_findings'])}")
            _metric_card(tcols[4], "Críticos", f"{int(tr['critical_findings'])}")
        c1, c2 = st.columns([2, 3])
        with c1:
            st.markdown("**Hallazgos de calidad por regla (§8, R01–R25)**")
            if not quality.empty:
                byrule = quality.groupby(["rule_id", "severity"]).size().reset_index(name="n")
                figq = px.bar(byrule, x="n", y="rule_id", color="severity", orientation="h",
                              color_discrete_map={"critica": "#b91c1c", "alta": "#f59e0b",
                                                  "media": "#38bdf8"})
                figq.update_layout(height=320, template="plotly_dark",
                                   margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(figq, use_container_width=True)
            else:
                st.success("Sin hallazgos de calidad de datos.")
        with c2:
            st.markdown("**Detalle de anomalías (con valor sugerido)**")
            if not quality.empty:
                st.dataframe(quality[["rule_id", "element_id", "severity", "evidence",
                                      "confidence", "suggested_value"]].head(200),
                             use_container_width=True, hide_index=True, height=320)
        ap = _filt(data["ap_anomalies"], fid)
        if not ap.empty:
            st.markdown("**Anomalías de alumbrado público (§10.3)**")
            st.dataframe(ap.groupby(["anomaly", "severity"]).size().reset_index(name="n"),
                         use_container_width=True, hide_index=True, height=140)
        st.markdown("**Zonas de protección — ramal como unidad de intervención (§7.5)**")
        if not zones.empty:
            st.dataframe(zones[["zone_id", "parent_zone", "n_nodes", "n_customers",
                                "n_tx_sites", "has_upstream_device"]],
                         use_container_width=True, hide_index=True, height=240)

    with tab_pf:
        if not pf.empty:
            pr = pf.iloc[0]
            pcols = st.columns(5)
            _metric_card(pcols[0], "Pérdida primaria", f"{pr['primary_loss_kw']:.1f} kW",
                         "Motor propio backward-forward sweep (§11)")
            _metric_card(pcols[1], "V mín (pu)", f"{pr['v_min_pu']:.4f}")
            _metric_card(pcols[2], "V máx (pu)", f"{pr['v_max_pu']:.4f}")
            _metric_card(pcols[3], "Convergió", "Sí" if pr["converged"] else "No")
            _metric_card(pcols[4], "Iteraciones", f"{int(pr['iterations'])}")
            st.caption("El motor propio se valida automáticamente contra OpenDSS "
                       "(tolerancia 2 % pérdidas / 0,5 % tensión, §11).")
        else:
            st.info("Sin resultados de flujo de potencia para este alimentador.")

    with tab_risk:
        st.markdown("**Ranking de riesgo de hurto — PU learning + no supervisado, "
                    "calibrado, con razones SHAP (§15)**")
        if not risk.empty:
            cols = ["customer_unit_id", "risk_score", "score_pu", "score_unsup",
                    "recoverable_kwh_month", "reason_1", "reason_2", "reason_3"]
            cols = [c for c in cols if c in risk.columns]
            top = risk.sort_values("risk_score", ascending=False).head(50)
            st.dataframe(top[cols], use_container_width=True, hide_index=True, height=420,
                         column_config={"risk_score": st.column_config.ProgressColumn(
                             "Riesgo", min_value=0, max_value=1, format="%.2f")})
            st.caption("Cada punto llega a campo con sus 3 razones en lenguaje operativo "
                       "(criterio §22.10). Score calibrado (isotónica) para el cálculo de "
                       "valor esperado en dólares.")

    with tab_plan:
        se = _filt(data["state_est"], fid)
        st.markdown("**Estimación de estado — carga no contabilizada por zona (§14.3)**")
        if not se.empty:
            figse = px.bar(se.sort_values("unaccounted_load_kw", ascending=False).head(20),
                           x="unaccounted_load_kw", y="zone_id", orientation="h",
                           color="max_norm_residual", color_continuous_scale="Reds")
            figse.update_layout(height=300, template="plotly_dark",
                                margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(figse, use_container_width=True)
            st.caption("Residuo normalizado alto + carga añadida ⇒ carga no contabilizada "
                       "aguas abajo (candidata a PNT localizada, WLS proporcional al residuo).")
        plan = _filt(data["plan"], fid)
        st.markdown("**Órdenes de trabajo priorizadas (puesto/poste, con checklist §17.5)**")
        if not plan.empty:
            cols = [c for c in ["site_id", "n_units", "benefit_usd", "roi", "cluster",
                                "crew", "day", "visit_seq", "checklist"] if c in plan.columns]
            st.dataframe(plan[cols].head(100), use_container_width=True,
                         hide_index=True, height=340)
        else:
            st.info("Este alimentador no tiene puestos seleccionados en el plan actual.")

    st.caption("Fases completas: F2 topología · F3/F5 balance · F4 flujo de potencia · "
               "F6 estimación de estado · F7 riesgo (PU+SHAP) · F8 priorización (OR-Tools).")


main()
