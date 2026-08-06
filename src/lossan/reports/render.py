"""Generación de reportes HTML/PDF (§18).

- Reporte ejecutivo por alimentador y consolidado regional (HTML, PDF opcional).
- Ficha de inspección por puesto/poste con mapa, razones y checklist.

Los gráficos se embeben como PNG base64 (autocontenido). El PDF se genera con
WeasyPrint si está instalado; si no, se entrega el HTML.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Template

from ..lakehouse import Lakehouse

_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;color:#1f2937;margin:28px;font-size:13px;}
h1{color:#0f172a;margin-bottom:0} .sub{color:#64748b;margin-top:4px;margin-bottom:14px}
h3{margin-top:22px;margin-bottom:6px;color:#0f172a}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:14px 0}
.kpi{background:#f1f5f9;border-radius:10px;padding:12px 10px;box-sizing:border-box;
     page-break-inside:avoid;text-align:center}
.kpi .v{font-size:20px;font-weight:700;white-space:nowrap} .kpi .l{color:#64748b;font-size:10.5px;margin-top:2px}
.note{color:#64748b;font-size:12px;margin:4px 0 10px 0}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:11px;table-layout:fixed}
tr{page-break-inside:avoid}
th,td{border:1px solid #e2e8f0;padding:4px 6px;text-align:left;overflow-wrap:break-word}
th{background:#f8fafc} img{max-width:100%} .foot{color:#94a3b8;font-size:11px;margin-top:24px}
.glossary table{font-size:12px} .glossary td:first-child{width:22%;font-weight:600}
"""

_CSS_LANDSCAPE = "@page{size:A4 landscape;margin:16mm}\n" + _CSS


def _fig_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _write(html: str, out_path: str | Path, pdf: bool) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if pdf and out.suffix.lower() == ".pdf":
        try:
            from weasyprint import HTML
            HTML(string=html).write_pdf(str(out))
            return out
        except Exception:
            out = out.with_suffix(".html")
    else:
        out = out.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    return out


_EXEC_TMPL = Template("""
<!doctype html><html><head><meta charset="utf-8"><style>{{css}}</style></head><body>
<h1>Reporte ejecutivo — Alimentador {{fid}}</h1>
<div class="sub">Análisis de pérdidas técnicas y no técnicas · periodo: {{n_months}} mes(es) · balance {{balance_icon}}</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{header_mwh}}</div><div class="l">Cabecera (MWh)</div></div>
  <div class="kpi"><div class="v">{{billed_mwh}}</div><div class="l">Facturado clientes (MWh)</div></div>
  <div class="kpi"><div class="v">{{ap_mwh}}</div><div class="l">Alumbrado público (MWh)</div></div>
  <div class="kpi"><div class="v">{{tech_mwh}}</div><div class="l">Técnicas (MWh)</div></div>
  <div class="kpi"><div class="v">{{pnt_mwh}}</div><div class="l">PNT (MWh)</div></div>
</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{pnt_pct}}%</div><div class="l">Pérdidas no técnicas (% cabecera)</div></div>
  <div class="kpi"><div class="v">{{tech_pct}}%</div><div class="l">Pérdidas técnicas (% cabecera)</div></div>
  <div class="kpi"><div class="v">{{n_over}}</div><div class="l">Puestos sobrecargados</div></div>
  <div class="kpi"><div class="v">{{cust_metered}}/{{cust_total}}</div><div class="l">Clientes con medidor</div></div>
  <div class="kpi"><div class="v">{{sl_metered}}/{{sl_total}}</div><div class="l">Luminarias con medidor propio</div></div>
</div>
<img src="{{chart}}"/>
<h3>Puestos de mayor cargabilidad</h3>{{sites_tbl}}
<h3>Clientes de mayor riesgo de hurto</h3>{{risk_tbl}}
{{glosario}}
<div class="foot">Generado por lossan · §18</div>
</body></html>""")


def executive_report(root: str, feeder_id: str, out_path: str, pdf: bool = True) -> Path:
    """Reporte ejecutivo por alimentador (HTML/PDF)."""
    lake = Lakehouse(root)
    bal = lake.read_entity("gold", "feeder_balance", feeder_id)
    load = lake.read_entity("gold", "transformer_loadability", feeder_id)
    risk = lake.read_entity("gold", "customer_risk", feeder_id)
    if bal.empty:
        raise ValueError(f"Sin balance para {feeder_id}. Ejecuta 'lossan run'.")
    b = bal.iloc[0]

    fig, ax = plt.subplots(figsize=(7, 3))
    ax.bar(["Facturada", "Alumbrado", "Técnicas", "PNT"],
           [b["energy_billed_kwh"], b["energy_streetlight_kwh"],
            b["energy_technical_kwh"], b["pnt_kwh"]],
           color=["#22c55e", "#f59e0b", "#3b82f6", "#ef4444"])
    ax.set_ylabel("kWh"); ax.set_title("Descomposición de la energía de cabecera")

    n_over = 0
    sites_tbl = "<p>—</p>"
    if not load.empty:
        n_over = int(load["loadability_class"].str.contains("overloaded").sum())
        sites_tbl = (load.sort_values("loadability", ascending=False)
                     [["site_id", "bank_config", "capacity_kva", "s_max_kva",
                       "loadability_class"]].head(10).to_html(index=False))
    risk_tbl = "<p>—</p>"
    if not risk.empty:
        cols = [c for c in ["customer_unit_id", "risk_score", "reason_1", "reason_2"]
                if c in risk.columns]
        risk_tbl = risk.sort_values("risk_score", ascending=False)[cols].head(10).to_html(index=False)

    html = _EXEC_TMPL.render(
        css=_CSS, fid=feeder_id,
        n_months=int(b.get("n_months", 0)),
        balance_icon="CIERRA" if b.get("balance_coherent") else "NO CIERRA",
        header_mwh=f"{b['energy_header_kwh']/1000:,.1f}",
        billed_mwh=f"{b['energy_billed_kwh']/1000:,.1f}",
        ap_mwh=f"{b['energy_streetlight_kwh']/1000:,.1f}",
        tech_mwh=f"{b['energy_technical_kwh']/1000:,.1f}",
        pnt_mwh=f"{b['pnt_kwh']/1000:,.1f}",
        pnt_pct=f"{b['pnt_pct']:.2f}", tech_pct=f"{b['technical_pct']:.2f}",
        cust_metered=f"{int(b.get('n_customers_metered', 0)):,}",
        cust_total=f"{int(b.get('n_customers', 0)):,}",
        sl_metered=f"{int(b.get('n_streetlights_metered', 0)):,}",
        sl_total=f"{int(b.get('n_streetlights', 0)):,}",
        n_over=n_over, chart=_fig_b64(fig), sites_tbl=sites_tbl, risk_tbl=risk_tbl,
        glosario=_GLOSARIO)
    return _write(html, out_path, pdf)


_GLOSARIO = """
<div class="glossary">
<h3>Cómo leer este reporte</h3>
<table>
<tr><th>Término</th><th>Qué significa</th></tr>
<tr><td><b>Energía de cabecera</b></td><td>Energía medida en el medidor de cabecera del alimentador (lo que "entra" a la red). Es el punto de partida del balance.</td></tr>
<tr><td><b>Energía facturada (clientes)</b></td><td>Suma del consumo registrado por los medidores de los clientes del sistema comercial, SOLO de los meses que coinciden con la cabecera (no se mezcla con histórico de otros periodos).</td></tr>
<tr><td><b>Alumbrado público (AP)</b></td><td>Energía que consume el alumbrado público — se conoce (por inventario de luminarias) pero normalmente NO se factura a un cliente, así que se resta aparte para no contarla como pérdida.</td></tr>
<tr><td><b>Pérdidas técnicas</b></td><td>Energía que se disipa físicamente en la red (calor en conductores y transformadores) por su propia naturaleza eléctrica — I²R en conductores, pérdidas de vacío y de carga en transformadores. Se calculan con la física real de la red (calibre de conductor, longitud, potencia de transformador), no se miden directamente.</td></tr>
<tr><td><b>PNT (Pérdidas No Técnicas)</b></td><td>Todo lo que NO se explica por facturación + AP + pérdidas técnicas. Es un residuo contable: <code>PNT = Cabecera − Facturado − AP − Técnicas</code>. Agrupa hurto de energía, errores de medición, fraude, y también <u>errores de datos</u> (topología mal armada, clientes mal asignados a su alimentador, etc.) — un PNT extremo (muy alto o negativo) es indicio de esto último, no necesariamente de hurto.</td></tr>
<tr><td><b>PNT negativo</b></td><td>Significa que lo facturado + AP + técnicas ya supera la cabecera del mismo periodo. Físicamente no debería pasar — casi siempre delata un problema de datos: clientes asociados al alimentador equivocado, cuentas duplicadas, o error en la medición de cabecera. Se prioriza para inspección/depuración de datos antes que para hurto.</td></tr>
<tr><td><b>Balance cerrado</b></td><td>El alimentador pasó las 5 validaciones internas de coherencia (PNT no negativo, todo dentro de cabecera, pérdidas totales y técnicas en rango plausible, cabecera positiva). "No cerrado" NO significa automáticamente PNT negativo — puede fallar por cualquiera de las 5 validaciones; revisar la columna "Motivo" del Top 10 para el detalle exacto de cada caso.</td></tr>
</table>
</div>
"""

_CONS_TMPL = Template("""
<!doctype html><html><head><meta charset="utf-8"><style>{{css}}</style></head><body>
<h1>Reporte consolidado regional</h1>
<div class="sub">{{n}} alimentadores · periodo: {{n_months}} mes(es) de cabecera</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{header_mwh}}</div><div class="l">Cabecera (MWh)</div></div>
  <div class="kpi"><div class="v">{{billed_mwh}}</div><div class="l">Facturado clientes (MWh)</div></div>
  <div class="kpi"><div class="v">{{ap_mwh}}</div><div class="l">Alumbrado público (MWh)</div></div>
  <div class="kpi"><div class="v">{{tech_mwh}}</div><div class="l">Pérdidas técnicas (MWh)</div></div>
  <div class="kpi"><div class="v">{{pnt_mwh}}</div><div class="l">PNT (MWh)</div></div>
</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{pnt}}%</div><div class="l">PNT global (% cabecera)</div></div>
  <div class="kpi"><div class="v">{{tech}}%</div><div class="l">Técnicas global (% cabecera)</div></div>
  <div class="kpi"><div class="v">{{closed}}/{{n}}</div><div class="l">Balances cerrados<br/>({{n_negative}} con PNT negativo)</div></div>
  <div class="kpi"><div class="v">{{cust_metered}}/{{cust_total}}</div><div class="l">Clientes con medidor registrado</div></div>
  <div class="kpi"><div class="v">{{sl_metered}}/{{sl_total}}</div><div class="l">Luminarias con medidor propio</div></div>
</div>
<p class="note">"Balances cerrados" NO equivale a "PNT negativo": un alimentador puede no cerrar por otras 4 razones distintas (ver glosario). De los {{n}} alimentadores, {{n_negative}} tienen PNT negativo (posible error de topología/asignación) y {{n_not_closed_other}} no cierran por otro motivo.</p>
<img src="{{chart}}"/>

<h3>Cabecera vs. energía explicada</h3>
<p class="note">Rojo = energía de cabecera. Azul = facturado + alumbrado público + pérdidas técnicas (todo lo que SÍ se explica). La diferencia entre las dos barras de cada alimentador es la PNT — si la barra azul es más alta que la roja, la PNT es negativa (sospecha de error de datos).</p>
<img src="{{chart2}}"/>

<h3>⚠ Top 10 alimentadores prioritarios (mayor sospecha de error de datos/topología o pérdida)</h3>
<p class="note">Ordenado por |PNT| descendente. Los que NO cierran balance son los candidatos más fuertes a revisión de topología/asignación de clientes antes que a campaña de hurto.</p>
{{top10_tbl}}

{{glosario}}

<h3>Todos los alimentadores (MWh y %)</h3>{{tbl}}
<div class="foot">Generado por lossan · §18</div></body></html>""")


def consolidated_report(root: str, out_path: str, pdf: bool = True) -> Path:
    """Reporte consolidado regional (todos los alimentadores)."""
    lake = Lakehouse(root)
    bal = lake.read_entity("gold", "feeder_balance")
    status = lake.read_entity("gold", "feeder_status")
    if bal.empty:
        raise ValueError("Sin resultados. Ejecuta 'lossan run'.")
    tot_h = bal["energy_header_kwh"].sum()
    pnt = 100 * bal["pnt_kwh"].sum() / tot_h
    tech = 100 * bal["energy_technical_kwh"].sum() / tot_h
    closed = int(status["balance_closed"].sum()) if not status.empty else 0
    n_months = int(bal["n_months"].iloc[0]) if "n_months" in bal.columns and len(bal) else 0
    n_negative = int((bal["pnt_pct"] < 0).sum())
    n_not_closed_other = max(0, len(bal) - closed - n_negative)
    cust_metered = int(bal.get("n_customers_metered", pd.Series(dtype=int)).sum())
    cust_total = int(bal["n_customers"].sum())
    sl_metered = int(bal.get("n_streetlights_metered", pd.Series(dtype=int)).sum())
    sl_total = int(bal["n_streetlights"].sum())

    fig, ax = plt.subplots(figsize=(8, 3))
    b = bal.sort_values("feeder_id")
    ax.bar(b["feeder_id"], b["technical_pct"], label="Técnicas", color="#3b82f6")
    ax.bar(b["feeder_id"], b["pnt_pct"], bottom=b["technical_pct"], label="PNT", color="#ef4444")
    ax.set_ylabel("% cabecera"); ax.legend(); ax.tick_params(axis="x", rotation=90)

    # --- Cabecera vs. explicado (facturado+AP+técnicas): la brecha ES la PNT ---
    b2 = bal.sort_values("feeder_id").copy()
    b2["explicado_mwh"] = (b2["energy_billed_kwh"] + b2["energy_streetlight_kwh"]
                           + b2["energy_technical_kwh"]) / 1000
    b2["header_mwh"] = b2["energy_header_kwh"] / 1000
    x = range(len(b2))
    fig2, ax2 = plt.subplots(figsize=(8, 3))
    w = 0.4
    ax2.bar([i - w / 2 for i in x], b2["header_mwh"], width=w, label="Cabecera", color="#ef4444")
    ax2.bar([i + w / 2 for i in x], b2["explicado_mwh"], width=w,
           label="Facturado + AP + Técnicas", color="#3b82f6")
    ax2.set_ylabel("MWh"); ax2.set_xticks(list(x)); ax2.set_xticklabels(b2["feeder_id"], rotation=90)
    ax2.legend(); ax2.set_title("Cabecera vs. energía explicada — la brecha es la PNT")

    # --- Top 10 prioritarios: |PNT| desc, con motivo explícito ---
    ranked = bal.copy()
    ranked["abs_pnt_pct"] = ranked["pnt_pct"].abs()
    if not status.empty:
        ranked = ranked.drop(columns=["failed_checks"], errors="ignore").merge(
            status[["feeder_id", "balance_closed", "failed_checks"]],
            on="feeder_id", how="left")
    else:
        ranked["balance_closed"], ranked["failed_checks"] = True, ""
    ranked = ranked.sort_values("abs_pnt_pct", ascending=False).head(10)
    ranked["Balance"] = ranked["balance_closed"].map({True: "cierra", False: "NO cierra"})
    ranked["Motivo"] = ranked.apply(
        lambda r: (f"No cierra: {r['failed_checks']}" if not r["balance_closed"]
                   else ("PNT muy alto — posible hurto, pero verificar AP/topología primero"
                         if r["pnt_pct"] > 0 else "PNT negativo — revisar asignación de clientes")),
        axis=1)
    ranked["Cabecera (MWh)"] = (ranked["energy_header_kwh"] / 1000).round(1)
    ranked["Facturado (MWh)"] = (ranked["energy_billed_kwh"] / 1000).round(1)
    ranked["AP (MWh)"] = (ranked["energy_streetlight_kwh"] / 1000).round(1)
    ranked["Técnicas (MWh)"] = (ranked["energy_technical_kwh"] / 1000).round(1)
    ranked["PNT (MWh)"] = (ranked["pnt_kwh"] / 1000).round(1)
    top10_cols = ["feeder_id", "Balance", "pnt_pct", "Cabecera (MWh)", "Facturado (MWh)",
                 "AP (MWh)", "Técnicas (MWh)", "PNT (MWh)", "n_customers", "Motivo"]
    top10_tbl = ranked.rename(columns={"feeder_id": "Alimentador", "pnt_pct": "PNT %",
                                       "n_customers": "Clientes"})[
        ["Alimentador", "Balance", "PNT %", "Cabecera (MWh)", "Facturado (MWh)", "AP (MWh)",
         "Técnicas (MWh)", "PNT (MWh)", "Clientes", "Motivo"]].to_html(index=False, float_format="%.2f")

    full = bal.copy()
    full["Cabecera (MWh)"] = (full["energy_header_kwh"] / 1000).round(1)
    full["Facturado (MWh)"] = (full["energy_billed_kwh"] / 1000).round(1)
    full["AP (MWh)"] = (full["energy_streetlight_kwh"] / 1000).round(1)
    full["Técnicas (MWh)"] = (full["energy_technical_kwh"] / 1000).round(1)
    full["PNT (MWh)"] = (full["pnt_kwh"] / 1000).round(1)
    tbl = (full.sort_values("pnt_pct", ascending=False)
           .rename(columns={"feeder_id": "Alimentador", "pnt_pct": "PNT %",
                            "technical_pct": "Técnicas %", "n_customers": "Clientes"})
           [["Alimentador", "Cabecera (MWh)", "Facturado (MWh)", "AP (MWh)", "Técnicas (MWh)",
             "PNT (MWh)", "PNT %", "Técnicas %", "Clientes"]]
           .to_html(index=False, float_format="%.2f"))

    html = _CONS_TMPL.render(
        css=_CSS_LANDSCAPE, n=len(bal), n_months=n_months, pnt=f"{pnt:.2f}", tech=f"{tech:.2f}",
        closed=closed, n_negative=n_negative, n_not_closed_other=n_not_closed_other,
        cust_metered=f"{cust_metered:,}", cust_total=f"{cust_total:,}",
        sl_metered=f"{sl_metered:,}", sl_total=f"{sl_total:,}",
        chart=_fig_b64(fig), chart2=_fig_b64(fig2),
        header_mwh=f"{tot_h/1000:,.1f}", billed_mwh=f"{bal['energy_billed_kwh'].sum()/1000:,.1f}",
        ap_mwh=f"{bal['energy_streetlight_kwh'].sum()/1000:,.1f}",
        tech_mwh=f"{bal['energy_technical_kwh'].sum()/1000:,.1f}",
        pnt_mwh=f"{bal['pnt_kwh'].sum()/1000:,.1f}",
        top10_tbl=top10_tbl, glosario=_GLOSARIO, tbl=tbl)
    return _write(html, out_path, pdf)


_INSP_TMPL = Template("""
<!doctype html><html><head><meta charset="utf-8"><style>{{css}}</style></head><body>
<h1>Ficha de inspección — Puesto {{sid}}</h1>
<div class="sub">Alimentador {{fid}} · Poste {{pole}}</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{n_units}}</div><div class="l">Unidades a revisar</div></div>
  <div class="kpi"><div class="v">{{roi}}</div><div class="l">ROI estimado</div></div>
  <div class="kpi"><div class="v">${{benefit}}</div><div class="l">Beneficio esperado</div></div>
</div>
<img src="{{map_img}}"/>
<h3>Checklist (razones del modelo)</h3><ul>{% for r in reasons %}<li>{{r}}</li>{% endfor %}</ul>
<h3>Unidades de cliente a revisar</h3>{{units_tbl}}
<div class="foot">Generado por lossan · §17.5 / §18 · cuadrilla: día {{day}}, ruta {{seq}}</div>
</body></html>""")


def inspection_sheet(root: str, site_id: str, out_path: str, pdf: bool = True) -> Path:
    """Ficha de inspección por puesto/poste para la cuadrilla."""
    lake = Lakehouse(root)
    plan = lake.read_entity("gold", "inspection_plan")
    customers = lake.read_entity("bronze", "customers")
    poles = lake.read_entity("bronze", "poles")
    risk = lake.read_entity("gold", "customer_risk")

    prow = plan[plan["site_id"] == site_id] if not plan.empty else pd.DataFrame()
    p = prow.iloc[0].to_dict() if not prow.empty else {}
    fid = p.get("feeder_id", "")
    site_customers = customers[customers["transformer_site_id"] == site_id] \
        if not customers.empty else pd.DataFrame()

    # mapa: poste del puesto entre los postes del alimentador
    map_img = ""
    if not poles.empty:
        fp = poles[poles["feeder_id"] == fid] if fid else poles
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.scatter(fp["x"], fp["y"], s=4, color="#cbd5e1")
        cust_p = site_customers.merge(poles[["pole_id", "x", "y"]], on="pole_id", how="left")
        if not cust_p.empty:
            ax.scatter(cust_p["x"], cust_p["y"], s=30, color="#ef4444", label="puesto")
            ax.legend()
        ax.set_title(f"Ubicación del puesto {site_id}"); ax.set_xticks([]); ax.set_yticks([])
        map_img = _fig_b64(fig)

    reasons = [p.get(k) for k in ("reason_1", "reason_2", "reason_3") if p.get(k)]
    if not reasons and not risk.empty and not site_customers.empty:
        rr = risk[risk["customer_unit_id"].isin(site_customers["customer_unit_id"])]
        if not rr.empty:
            top = rr.sort_values("risk_score", ascending=False).iloc[0]
            reasons = [top.get(k) for k in ("reason_1", "reason_2", "reason_3") if top.get(k)]

    units_tbl = "<p>—</p>"
    if not site_customers.empty:
        cols = ["customer_unit_id", "tariff_class"]
        st = site_customers[cols].copy()
        if not risk.empty:
            st = st.merge(risk[["customer_unit_id", "risk_score"]], on="customer_unit_id", how="left")
            st = st.sort_values("risk_score", ascending=False)
        units_tbl = st.head(30).to_html(index=False)

    html = _INSP_TMPL.render(
        css=_CSS, sid=site_id, fid=fid, pole=p.get("pole_id", "—"),
        n_units=int(p.get("n_units", len(site_customers))),
        roi=f"{p.get('roi', 0):.1f}" if p.get("roi") else "—",
        benefit=f"{p.get('benefit_usd', 0):,.0f}" if p.get("benefit_usd") else "—",
        map_img=map_img, reasons=reasons or ["(sin razones registradas)"],
        units_tbl=units_tbl, day=p.get("day", "—"), seq=p.get("visit_seq", "—"))
    return _write(html, out_path, pdf)
