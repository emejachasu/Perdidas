"""Grafo por alimentador con ``rustworkx`` y trazas (§6).

Reconstruye la topología en un grafo propio, independiente de arcpy (§2.5).
El grafo es dirigido desde la fuente hacia las cargas. Incluye las trazas
requeridas: ``trace_downstream``, ``trace_upstream``, ``path_to_source``
(con distancia e impedancia acumulada), ``subtree_load`` y
``branch_decomposition``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd
import rustworkx as rx


@dataclass
class FeederGraph:
    feeder_id: str
    source: str
    g: rx.PyDiGraph
    idx: dict[str, int]                       # node name -> index
    name: dict[int, str] = field(default_factory=dict)
    parent: dict[str, str] = field(default_factory=dict)   # node -> upstream node
    # Conjuntos explícitos de hojas (no se infieren del nombre del nodo).
    customer_nodes: set[str] = field(default_factory=set)
    streetlight_nodes: set[str] = field(default_factory=set)

    # ---------------- construcción ----------------
    @classmethod
    def build(cls, feeder_id: str, segments: pd.DataFrame,
              sites: pd.DataFrame | None = None,
              customers: pd.DataFrame | None = None,
              streetlights: pd.DataFrame | None = None) -> "FeederGraph":
        g = rx.PyDiGraph(check_cycle=False)
        idx: dict[str, int] = {}
        name: dict[int, str] = {}

        def node(n: str) -> int:
            if n not in idx:
                i = g.add_node(n)
                idx[n] = i
                name[i] = n
            return idx[n]

        source = f"{feeder_id}-SRC"
        node(source)
        parent: dict[str, str] = {}

        for r in segments.itertuples():
            u, v = node(r.node_from), node(r.node_to)
            z = complex(r.r_ohm_per_km, r.x_ohm_per_km) * (r.length_m / 1000.0)
            g.add_edge(u, v, {
                "segment_id": r.segment_id, "length_m": r.length_m,
                "z": z, "phase": r.phase, "voltage_ll": r.voltage_ll,
                "section": getattr(r, "section", None),
                "is_transformer": False,
            })
            parent[r.node_to] = r.node_from

        # aristas de transformador: nodo primario del puesto -> nodo secundario
        if sites is not None:
            for r in sites.itertuples():
                nid = getattr(r, "node_id", None)
                if nid is None:
                    continue
                sec = f"{nid}_S"
                if nid in idx and sec in idx:
                    g.add_edge(idx[nid], idx[sec], {
                        "segment_id": f"{r.site_id}-TX", "length_m": 0.0,
                        "z": complex(0, 0), "phase": "ABC",
                        "voltage_ll": None, "section": "transformer",
                        "is_transformer": True,
                    })
                    parent[sec] = nid
        fg = cls(feeder_id, source, g, idx, name, parent)
        fg.register_leaf_nodes(customers, streetlights)
        return fg

    # ---------------- trazas ----------------
    def trace_downstream(self, node: str) -> list[str]:
        """Todos los elementos aguas abajo de un nodo."""
        if node not in self.idx:
            return []
        desc = rx.descendants(self.g, self.idx[node])
        return [self.name[i] for i in desc]

    def trace_upstream(self, node: str) -> list[str]:
        """Todos los elementos aguas arriba de un nodo (hasta la fuente)."""
        if node not in self.idx:
            return []
        anc = rx.ancestors(self.g, self.idx[node])
        return [self.name[i] for i in anc]

    def path_to_source(self, node: str) -> dict:
        """Camino a la fuente con distancia (m) e impedancia acumulada (Ω)."""
        path = [node]
        dist_m, z = 0.0, complex(0, 0)
        cur = node
        seen = set()
        while cur in self.parent and cur not in seen:
            seen.add(cur)
            up = self.parent[cur]
            edge = self.g.get_edge_data(self.idx[up], self.idx[cur])
            dist_m += edge["length_m"]
            z += edge["z"]
            path.append(up)
            cur = up
        path.reverse()
        return {"path": path, "distance_m": round(dist_m, 3),
                "impedance_ohm": z, "reaches_source": path[0] == self.source}

    def subtree_load(self, node: str, load_map: dict[str, float] | None = None,
                     customer_nodes: set[str] | None = None,
                     streetlight_nodes: set[str] | None = None) -> dict:
        """Carga acumulada aguas abajo: nº clientes/luminarias y kVA (§6).

        Los clientes y luminarias se identifican por **conjuntos explícitos** de
        ids (``customer_nodes`` / ``streetlight_nodes``), no por convención de
        nombres: con los ids reales del SIG cualquier heurística de substring
        produce falsos positivos y negativos. Si no se pasan, se usan los
        registrados con :meth:`register_leaf_nodes`.
        """
        downstream = self.trace_downstream(node)
        cust = customer_nodes if customer_nodes is not None else self.customer_nodes
        lights = streetlight_nodes if streetlight_nodes is not None else self.streetlight_nodes
        kva = 0.0
        if load_map:
            kva = sum(load_map.get(n, 0.0) for n in downstream)
        n_cust = sum(1 for n in downstream if n in cust) if cust else 0
        n_light = sum(1 for n in downstream if n in lights) if lights else 0
        return {"n_customers": n_cust, "n_streetlights": n_light,
                "load_kva": round(kva, 3), "n_nodes": len(downstream)}

    def register_leaf_nodes(self, customers: "pd.DataFrame | None" = None,
                            streetlights: "pd.DataFrame | None" = None) -> None:
        """Registra qué nodos son clientes y cuáles luminarias (§6).

        Debe llamarse tras construir el grafo para que ``subtree_load`` cuente
        correctamente con los identificadores reales del SIG.
        """
        if customers is not None and not customers.empty:
            self.customer_nodes = set(customers["customer_unit_id"].astype(str))
        if streetlights is not None and not streetlights.empty:
            col = ("streetlight_id" if "streetlight_id" in streetlights.columns
                   else streetlights.columns[0])
            self.streetlight_nodes = set(streetlights[col].astype(str))

    def accumulate_downstream(self, load_map: dict[str, float]) -> dict[str, float]:
        """Carga acumulada aguas abajo de CADA nodo en una sola pasada.

        Equivale a llamar ``subtree_load`` en todos los nodos, pero en O(V+E) en
        vez de O(V·(V+E)): recorre el árbol en post-orden sumando hacia arriba.
        """
        acc = {n: float(load_map.get(n, 0.0)) for n in self.idx}
        try:
            order = rx.topological_sort(self.g)
        except rx.DAGHasCycle:
            return acc
        for i in reversed(list(order)):
            node = self.name[i]
            parent = self.parent.get(node)
            if parent is not None:
                acc[parent] = acc.get(parent, 0.0) + acc[node]
        return acc

    def branch_decomposition(self) -> list[dict]:
        """Descompone el árbol en ramas entre nodos de bifurcación (§6)."""
        branches, seg = [], []
        for i in self.g.node_indices():
            if self.g.out_degree(i) > 1 or i == self.idx[self.source]:
                for child in self.g.successor_indices(i):
                    seg.append((i, child))
        for u, v in seg:
            branches.append({"from": self.name[u], "to": self.name[v]})
        return branches

    # ---------------- validaciones (§6) ----------------
    def validate(self) -> list[dict]:
        findings = []
        # radialidad: ciclos
        try:
            rx.topological_sort(self.g)
        except rx.DAGHasCycle:
            findings.append({"rule": "TOPO_CYCLE", "severity": "critica",
                             "evidence": "El grafo del alimentador contiene ciclos (no radial)"})
        # islas: nodos no alcanzables desde la fuente
        reachable = rx.descendants(self.g, self.idx[self.source])
        reachable.add(self.idx[self.source])
        islands = [self.name[i] for i in self.g.node_indices() if i not in reachable]
        if islands:
            findings.append({"rule": "TOPO_ISLAND", "severity": "critica",
                             "evidence": f"{len(islands)} nodos no alcanzables desde la fuente",
                             "elements": islands[:20]})
        # multi-alimentación: nodo con in-degree > 1
        multi = [self.name[i] for i in self.g.node_indices() if self.g.in_degree(i) > 1]
        if multi:
            findings.append({"rule": "TOPO_MULTIFEED", "severity": "alta",
                             "evidence": f"{len(multi)} nodos con más de un padre",
                             "elements": multi[:20]})
        return findings

    @property
    def n_nodes(self) -> int:
        return self.g.num_nodes()

    @property
    def n_edges(self) -> int:
        return self.g.num_edges()
