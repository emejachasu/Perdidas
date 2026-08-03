"""Flujo de potencia trifásico desbalanceado — backward-forward sweep (§11).

Modelo por matriz de impedancia serie 3×3 por tramo (con acoplamiento mutuo,
Carson/Kron), cargas de potencia constante por fase y **corriente de neutro**
por rama. Extiende el motor monofásico equivalente (`sweep.py`) para los niveles
N2/N3 y para el análisis de desbalance (§14.2).
"""
from __future__ import annotations

import cmath
from dataclasses import dataclass, field

import numpy as np

A = cmath.exp(-1j * 2 * cmath.pi / 3)   # operador 1∠-120°


@dataclass
class ThreePhaseNetwork:
    """Red radial trifásica.

    branches: ``(from_idx, to_idx, Z)`` con Z matriz 3×3 compleja (Ω).
    loads_kva: por nodo, vector complejo de 3 fases (kW + j·kVAr) por fase.
    v_base_ln: tensión base línea-neutro [V].
    """
    nodes: list[str]
    branches: list[tuple[int, int, np.ndarray]]
    loads_kva: list[np.ndarray]
    v_base_ln: float
    node_index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.node_index:
            self.node_index = {n: i for i, n in enumerate(self.nodes)}


@dataclass
class Sweep3phResult:
    voltages: list[np.ndarray]           # 3-vector por nodo [V]
    branch_currents: list[np.ndarray]    # 3-vector por rama [A]
    neutral_currents: list[float]        # |In| por rama [A]
    branch_losses_kw: list[float]
    total_loss_kw: float
    iterations: int
    converged: bool
    v_min_pu: float
    max_unbalance_pct: float


def _source_voltage(v0: float) -> np.ndarray:
    return np.array([v0, v0 * A, v0 * A.conjugate()], dtype=complex)


def solve_bfs_3ph(net: ThreePhaseNetwork, tol: float = 1e-6,
                  max_iter: int = 100) -> Sweep3phResult:
    """Resuelve el flujo trifásico desbalanceado por barrido atrás/adelante."""
    n = len(net.nodes)
    v0 = net.v_base_ln
    Vsrc = _source_voltage(v0)
    V = [Vsrc.copy() for _ in range(n)]

    children: dict[int, list[int]] = {i: [] for i in range(n)}
    parent: dict[int, tuple[int, np.ndarray]] = {}
    for (u, v, z) in net.branches:
        children[u].append(v)
        parent[v] = (u, z)
    order = [0]; qi = 0
    while qi < len(order):
        cur = order[qi]; qi += 1
        order.extend(children[cur])
    reverse = list(reversed(order))

    branch_I = {v: np.zeros(3, dtype=complex) for (_, v, _) in net.branches}
    it = 0
    for it in range(1, max_iter + 1):
        # corriente de carga por fase (potencia constante)
        node_I = []
        for i in range(n):
            s = net.loads_kva[i] * 1000.0     # VA por fase
            vi = V[i].copy()
            vi[np.abs(vi) < 1e-6] = v0
            node_I.append(np.conj(s / vi))
        acc = [ni.copy() for ni in node_I]
        for v in reverse:
            if v in parent:
                u, _ = parent[v]
                acc[u] += acc[v]
                branch_I[v] = acc[v]
        maxdv = 0.0
        for v in order:
            if v in parent:
                u, z = parent[v]
                newV = V[u] - z @ branch_I[v]
                maxdv = max(maxdv, float(np.max(np.abs(newV - V[v]))))
                V[v] = newV
        if maxdv < tol * v0:
            break

    losses, currents, neutrals = [], [], []
    total = 0.0
    for (u, v, z) in net.branches:
        I = branch_I[v]
        ploss = float(np.real(np.conj(I) @ (z @ I))) / 1000.0   # kW
        losses.append(ploss); total += ploss
        currents.append(I)
        neutrals.append(float(abs(I[0] + I[1] + I[2])))

    vmags = [float(np.min(np.abs(v))) / v0 for v in V]
    # desbalance de corriente en la rama de cabecera
    if currents:
        mags = np.abs(currents[0])
        avg = mags.mean() if mags.mean() > 0 else 1.0
        unbal = float(np.max(np.abs(mags - avg)) / avg * 100)
    else:
        unbal = 0.0
    return Sweep3phResult(
        voltages=V, branch_currents=currents, neutral_currents=neutrals,
        branch_losses_kw=losses, total_loss_kw=total, iterations=it,
        converged=(it < max_iter), v_min_pu=min(vmags), max_unbalance_pct=unbal)


def zmatrix_from_sequence(z1: complex, z0: complex, length_km: float) -> np.ndarray:
    """Matriz de fase 3×3 a partir de impedancias de secuencia (Z1, Z0).

    Zs = (Z0 + 2·Z1)/3 (propia), Zm = (Z0 − Z1)/3 (mutua). Escalada por longitud.
    """
    zs = (z0 + 2 * z1) / 3.0
    zm = (z0 - z1) / 3.0
    Z = np.array([[zs, zm, zm], [zm, zs, zm], [zm, zm, zs]], dtype=complex)
    return Z * length_km
