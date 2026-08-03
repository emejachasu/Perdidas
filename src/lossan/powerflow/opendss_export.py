"""Exportador a OpenDSS (§11).

Genera un ``.dss`` completo (Circuit, Line con R/X explícitas, Load, y
Transformer por unidad con su conexión de banco) desde el modelo canónico o
desde una RadialNetwork. Uso en niveles N2/N3 y para validación cruzada.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from ..domain.enums import BankConfig
from .sweep import RadialNetwork

_BANK_CONN = {
    BankConfig.SINGLE: "wye",
    BankConfig.WYE_CLOSED: "wye",
    BankConfig.DELTA_CLOSED: "delta",
    BankConfig.OPEN_DELTA: "delta",
    BankConfig.OPEN_WYE_OPEN_DELTA: "delta",
    BankConfig.DELTA_4WIRE: "delta",
}


def _bus(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]", "_", name)


def export_dss(net: RadialNetwork, out_path: str | Path,
               circuit_name: str = "feeder") -> Path:
    """Escribe el modelo de la RadialNetwork como ``.dss`` y lo devuelve."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    v_ll_kv = net.v_base_ln * math.sqrt(3) / 1000.0
    lines = []
    lines.append(f"Clear")
    src = _bus(net.nodes[0])
    lines.append(
        f"New Circuit.{circuit_name} basekv={v_ll_kv:.4f} pu=1.0 phases=3 "
        f"bus1={src} MVAsc3=100000 MVAsc1=100000"
    )
    # Líneas con R/X explícitas (Length=1 -> ohms totales)
    for k, (u, v, z) in enumerate(net.branches):
        r = max(z.real, 1e-6)
        x = max(z.imag, 1e-6)
        lines.append(
            f"New Line.L{k} phases=3 bus1={_bus(net.nodes[u])} bus2={_bus(net.nodes[v])} "
            f"R1={r:.6f} X1={x:.6f} R0={3*r:.6f} X0={3*x:.6f} Length=1 units=none"
        )
    # Cargas de potencia constante (kW/kvar)
    for i, s in enumerate(net.loads_kva):
        if abs(s) <= 0:
            continue
        lines.append(
            f"New Load.LD{i} phases=3 bus1={_bus(net.nodes[i])} kv={v_ll_kv:.4f} "
            f"kW={s.real:.4f} kvar={s.imag:.4f} model=1 conn=wye"
        )
    lines.append(f"Set voltagebases=[{v_ll_kv:.4f}]")
    lines.append("CalcVoltageBases")
    lines.append("New Energymeter.M1 element=Line.L0 terminal=1")
    lines.append("Solve")
    out.write_text("\n".join(lines) + "\n")
    return out


def transformer_dss(site_id: str, bank_config: BankConfig, units,
                    hv_kv: float, lv_kv: float, bus_hv: str, bus_lv: str) -> list[str]:
    """Genera definiciones Transformer POR UNIDAD con su conexión de banco (§11)."""
    conn = _BANK_CONN.get(bank_config, "wye")
    out = []
    for j, u in enumerate(units):
        out.append(
            f"New Transformer.{_bus(site_id)}_U{j} phases=3 windings=2 "
            f"xhl={(u.get('z_pct') or 5.0):.2f} "
            f"~ wdg=1 bus={bus_hv} conn={conn} kv={hv_kv:.3f} kva={u['sn_kva']:.1f} "
            f"%loadloss={100*u['pk_kw']/u['sn_kva']:.3f} %noloadloss={100*u['p0_kw']/u['sn_kva']:.3f} "
            f"~ wdg=2 bus={bus_lv} conn=wye kv={lv_kv:.3f} kva={u['sn_kva']:.1f}"
        )
    return out


def export_dss_3ph(net, out_path: str | Path, circuit_name: str = "feeder3ph") -> Path:
    """Escribe una ThreePhaseNetwork como ``.dss`` con líneas de matriz 3×3 y
    cargas por fase (desbalanceadas)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    v_ln_kv = net.v_base_ln / 1000.0
    v_ll_kv = v_ln_kv * math.sqrt(3)
    lines = ["Clear"]
    src = _bus(net.nodes[0])
    lines.append(f"New Circuit.{circuit_name} basekv={v_ll_kv:.5f} pu=1.0 phases=3 "
                 f"bus1={src} MVAsc3=100000 MVAsc1=100000")
    for k, (u, v, z) in enumerate(net.branches):
        r = z.real; x = z.imag
        rm = f"{r[0,0]:.6f} | {r[1,0]:.6f} {r[1,1]:.6f} | {r[2,0]:.6f} {r[2,1]:.6f} {r[2,2]:.6f}"
        xm = f"{x[0,0]:.6f} | {x[1,0]:.6f} {x[1,1]:.6f} | {x[2,0]:.6f} {x[2,1]:.6f} {x[2,2]:.6f}"
        lines.append(f"New Line.L{k} phases=3 bus1={_bus(net.nodes[u])}.1.2.3 "
                     f"bus2={_bus(net.nodes[v])}.1.2.3 rmatrix=({rm}) xmatrix=({xm}) "
                     f"Length=1 units=none")
    for i, s in enumerate(net.loads_kva):
        for ph in range(3):
            if abs(s[ph]) <= 0:
                continue
            lines.append(f"New Load.LD{i}_{ph+1} phases=1 bus1={_bus(net.nodes[i])}.{ph+1} "
                         f"kv={v_ln_kv:.5f} kW={s[ph].real:.4f} kvar={s[ph].imag:.4f} model=1")
    lines.append(f"Set voltagebases=[{v_ll_kv:.5f}]")
    lines.append("CalcVoltageBases")
    lines.append("New Energymeter.M1 element=Line.L0 terminal=1")
    lines.append("Solve")
    out.write_text("\n".join(lines) + "\n")
    return out


def solve_with_opendss(dss_path: str | Path) -> dict | None:
    """Resuelve el ``.dss`` con OpenDSSDirect y devuelve pérdidas totales [kW].

    Devuelve None si OpenDSSDirect no está instalado.
    """
    try:
        import opendssdirect as dss
    except Exception:
        return None
    dss.Command(f'Redirect "{Path(dss_path).resolve()}"')
    losses = dss.Circuit.Losses()   # (P, Q) en watts
    total_power = dss.Circuit.TotalPower()  # kW (negativo = entregado)
    return {
        "total_loss_kw": losses[0] / 1000.0,
        "total_loss_kvar": losses[1] / 1000.0,
        "total_power_kw": total_power[0],
        "converged": dss.Solution.Converged(),
    }
