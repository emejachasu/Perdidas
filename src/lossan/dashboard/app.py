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
    }


def _metric_card(col, label, value, help_text=""):
    col.metric(label, value, help=help_text)


def main() -> None:
    st.markdown(
        "<h1 style='margin-bottom:0'>⚡ Plataforma de Pérdidas — Avance por Alimentador</h1>"
        "<p style='color:#94a3b8;margin-top:4px'>Análisis técnico vs. no técnico · "
        "F0 fundacional · balance jerárquico y cargabilidad por puesto</p>",
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
    if bal["pnt_negative_alert"]:
        st.error("⚠️ PNT < 0: error inequívoco de balance (§13). Primera hipótesis: "
                 "transferencia entre alimentadores no registrada.")

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Descomposición del balance de energía (§13)**")
        waterfall = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "relative"],
            x=["Cabecera", "− Facturada", "− Alumbrado público", "− Técnicas", "= PNT"],
            y=[bal["energy_header_kwh"], -bal["energy_billed_kwh"],
               -bal["energy_streetlight_kwh"], -bal["energy_technical_kwh"], 0],
            connector={"line": {"color": "#475569"}},
        ))
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
        else:
            st.info("Sin datos de cargabilidad para este alimentador.")

    m1, m2 = st.columns(2)
    with m1:
        st.markdown("**Puestos de transformación (cargabilidad por configuración de banco)**")
        if not load.empty:
            st.dataframe(
                load[["site_id", "bank_config", "n_units", "capacity_kva",
                      "s_max_kva", "loadability", "loadability_class", "bank_quality_flags"]]
                .sort_values("loadability", ascending=False),
                use_container_width=True, hide_index=True, height=320)
    with m2:
        st.markdown("**Ranking de riesgo de clientes (proxy M1 — caída/recuperación)**")
        if not risk.empty:
            top = risk.sort_values("risk_score", ascending=False).head(30)
            st.dataframe(top[["customer_unit_id", "risk_score", "flagged_drop"]],
                         use_container_width=True, hide_index=True, height=320)
            st.caption(f"Clientes marcados por caída sostenida: "
                       f"{int(risk['flagged_drop'].sum())} de {len(risk)}")

    st.caption("F0 fundacional. Fases F4/F6/F8 (flujo de potencia detallado, "
               "estimación de estado, optimización de campaña con OR-Tools) en roadmap.")


main()
