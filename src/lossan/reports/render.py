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
body{font-family:Segoe UI,Arial,sans-serif;color:#1f2937;margin:32px;}
h1{color:#0f172a;margin-bottom:0} .sub{color:#64748b;margin-top:4px}
.kpis{display:flex;gap:18px;flex-wrap:wrap;margin:18px 0}
.kpi{background:#f1f5f9;border-radius:10px;padding:14px 18px;min-width:130px}
.kpi .v{font-size:26px;font-weight:700} .kpi .l{color:#64748b;font-size:12px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th,td{border:1px solid #e2e8f0;padding:6px 8px;text-align:left}
th{background:#f8fafc} img{max-width:100%} .foot{color:#94a3b8;font-size:11px;margin-top:24px}
"""


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
<div class="sub">Análisis de pérdidas técnicas y no técnicas</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{header_gwh}}</div><div class="l">Energía cabecera (GWh)</div></div>
  <div class="kpi"><div class="v">{{pnt_pct}}%</div><div class="l">Pérdidas no técnicas</div></div>
  <div class="kpi"><div class="v">{{tech_pct}}%</div><div class="l">Pérdidas técnicas</div></div>
  <div class="kpi"><div class="v">{{n_over}}</div><div class="l">Puestos sobrecargados</div></div>
</div>
<img src="{{chart}}"/>
<h3>Puestos de mayor cargabilidad</h3>{{sites_tbl}}
<h3>Clientes de mayor riesgo de hurto</h3>{{risk_tbl}}
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
        css=_CSS, fid=feeder_id, header_gwh=f"{b['energy_header_kwh']/1e6:.2f}",
        pnt_pct=f"{b['pnt_pct']:.2f}", tech_pct=f"{b['technical_pct']:.2f}",
        n_over=n_over, chart=_fig_b64(fig), sites_tbl=sites_tbl, risk_tbl=risk_tbl)
    return _write(html, out_path, pdf)


_CONS_TMPL = Template("""
<!doctype html><html><head><meta charset="utf-8"><style>{{css}}</style></head><body>
<h1>Reporte consolidado regional</h1>
<div class="sub">{{n}} alimentadores</div>
<div class="kpis">
  <div class="kpi"><div class="v">{{pnt}}%</div><div class="l">PNT global</div></div>
  <div class="kpi"><div class="v">{{tech}}%</div><div class="l">Técnicas global</div></div>
  <div class="kpi"><div class="v">{{closed}}/{{n}}</div><div class="l">Balances cerrados</div></div>
</div>
<img src="{{chart}}"/>
<h3>Alimentadores por PNT</h3>{{tbl}}
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

    fig, ax = plt.subplots(figsize=(8, 3))
    b = bal.sort_values("feeder_id")
    ax.bar(b["feeder_id"], b["technical_pct"], label="Técnicas", color="#3b82f6")
    ax.bar(b["feeder_id"], b["pnt_pct"], bottom=b["technical_pct"], label="PNT", color="#ef4444")
    ax.set_ylabel("% cabecera"); ax.legend(); ax.tick_params(axis="x", rotation=90)

    tbl = (bal.sort_values("pnt_pct", ascending=False)
           [["feeder_id", "pnt_pct", "technical_pct", "total_losses_pct", "n_customers"]]
           .to_html(index=False))
    html = _CONS_TMPL.render(css=_CSS, n=len(bal), pnt=f"{pnt:.2f}", tech=f"{tech:.2f}",
                             closed=closed, chart=_fig_b64(fig), tbl=tbl)
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
