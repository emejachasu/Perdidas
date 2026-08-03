"""Motor propio de flujo de potencia backward-forward sweep (§11).

Para redes radiales. Objetivo: < 100 ms por escenario en un alimentador típico,
para permitir barridos masivos y Monte Carlo. Modelo de secuencia positiva
(balanceado) con cargas de potencia constante; extensible a trifásico
desbalanceado con matriz de impedancias (Carson/Kron) en N3.
"""
from __future__ import annotations

import cmath
from dataclasses import dataclass, field


@dataclass
class RadialNetwork:
    """Red radial en un nivel de tensión.

    nodes: lista de nombres (nodes[0] es la fuente).
    branches: (from_idx, to_idx, Z_ohm) con el árbol dirigido desde la fuente.
    loads_kva: S compleja por nodo (kW + j kVAr).
    v_base_ln: tensión base línea-neutro [V].
    three_phase: si True, potencias trifásicas y V_base línea-línea/√3.
    """
    nodes: list[str]
    branches: list[tuple[int, int, complex]]
    loads_kva: list[complex]
    v_base_ln: float
    three_phase: bool = True
    node_index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.node_index:
            self.node_index = {n: i for i, n in enumerate(self.nodes)}


@dataclass
class SweepResult:
    voltages_ln: list[complex]          # tensión línea-neutro por nodo [V]
    branch_currents: list[complex]      # corriente por rama [A]
    branch_losses_kw: list[float]       # pérdidas por rama [kW]
    total_loss_kw: float
    iterations: int
    converged: bool
    v_min_pu: float
    v_max_pu: float


def solve_bfs(net: RadialNetwork, tol: float = 1e-6, max_iter: int = 100) -> SweepResult:
    """Resuelve el flujo por barrido hacia atrás/adelante (backward-forward sweep).

    Devuelve tensiones por nodo, corrientes y pérdidas por rama, y el total.
    """
    n = len(net.nodes)
    phases = 3.0 if net.three_phase else 1.0
    v0 = net.v_base_ln
    V = [complex(v0, 0.0) for _ in range(n)]

    # orden topológico: hojas primero para el barrido hacia atrás
    children: dict[int, list[int]] = {i: [] for i in range(n)}
    parent_branch: dict[int, tuple[int, complex]] = {}
    for (u, v, z) in net.branches:
        children[u].append(v)
        parent_branch[v] = (u, z)
    # orden BFS desde la fuente (0)
    order = [0]
    qi = 0
    while qi < len(order):
        cur = order[qi]; qi += 1
        order.extend(children[cur])
    reverse = list(reversed(order))

    branch_I = {v: complex(0, 0) for (_, v, _) in net.branches}
    it = 0
    for it in range(1, max_iter + 1):
        # corriente inyectada por carga (potencia constante) en cada nodo
        node_I = []
        for i in range(n):
            s = net.loads_kva[i] * 1000.0 / phases   # VA por fase
            vi = V[i] if abs(V[i]) > 1e-6 else complex(v0, 0)
            node_I.append((s / vi).conjugate() if abs(s) > 0 else complex(0, 0))

        # backward sweep: corriente de rama = carga del nodo + ramas hijas
        acc = list(node_I)
        for v in reverse:
            if v in parent_branch:
                u, _ = parent_branch[v]
                acc[u] += acc[v]
                branch_I[v] = acc[v]

        # forward sweep: actualizar tensiones
        maxdv = 0.0
        for v in order:
            if v in parent_branch:
                u, z = parent_branch[v]
                newV = V[u] - branch_I[v] * z
                maxdv = max(maxdv, abs(newV - V[v]))
                V[v] = newV
        if maxdv < tol * v0:
            break

    losses, total = [], 0.0
    branch_currents = []
    for (u, v, z) in net.branches:
        I = branch_I[v]
        ploss = phases * (abs(I) ** 2) * z.real / 1000.0   # kW
        losses.append(ploss)
        total += ploss
        branch_currents.append(I)

    vmags = [abs(v) / v0 for v in V]
    return SweepResult(
        voltages_ln=V, branch_currents=branch_currents, branch_losses_kw=losses,
        total_loss_kw=total, iterations=it, converged=(it < max_iter),
        v_min_pu=min(vmags), v_max_pu=max(vmags),
    )


def network_from_feeder(fg, segments, load_map: dict[str, float],
                        v_base_ln: float, pf: float = 0.92,
                        section: str = "primary") -> RadialNetwork:
    """Construye una RadialNetwork de un nivel a partir del grafo del alimentador.

    Agrega la carga aguas abajo de cada nodo (kVA con factor de potencia ``pf``)
    en el nodo. Usa los tramos de la sección indicada.
    """
    segs = segments[segments["section"] == section]
    node_set = {fg.source}
    for r in segs.itertuples():
        node_set.add(r.node_from)
        node_set.add(r.node_to)
    nodes = [fg.source] + sorted(node_set - {fg.source})
    nidx = {nm: i for i, nm in enumerate(nodes)}

    branches = []
    for r in segs.itertuples():
        if r.node_from in nidx and r.node_to in nidx:
            z = complex(r.r_ohm_per_km, r.x_ohm_per_km) * (r.length_m / 1000.0)
            branches.append((nidx[r.node_from], nidx[r.node_to], z))

    tanphi = cmath.acos(pf).real
    q_factor = cmath.tan(cmath.acos(pf)).real
    loads = [complex(0, 0)] * len(nodes)
    for nm, i in nidx.items():
        p_kw = load_map.get(nm, 0.0)
        loads[i] = complex(p_kw, p_kw * q_factor)

    return RadialNetwork(nodes=nodes, branches=branches, loads_kva=loads,
                         v_base_ln=v_base_ln, three_phase=True, node_index=nidx)
