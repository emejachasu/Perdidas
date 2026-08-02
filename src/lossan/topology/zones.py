"""Zonas de protección (§7.5).

Un dispositivo segmenta la red: la zona son los elementos aguas abajo de un
dispositivo hasta el siguiente. Es la definición correcta de "ramal": la unidad
que una cuadrilla puede aislar, medir e intervenir.
"""
from __future__ import annotations

from collections import deque

import pandas as pd

from .graph import FeederGraph


def build_protection_zones(fg: FeederGraph, devices: pd.DataFrame,
                           sites: pd.DataFrame | None = None,
                           customers: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Genera el árbol de zonas y el mapeo nodo -> zona.

    Devuelve ``(zones_df, node_to_zone)``.
    """
    boundaries = {fg.source: "HEAD"}
    if devices is not None and not devices.empty:
        for r in devices.itertuples():
            boundaries[r.node_id] = r.device_id

    node_to_zone: dict[str, str] = {}
    zone_members: dict[str, list[str]] = {z: [] for z in boundaries.values()}

    # BFS desde cada frontera, deteniendo el descenso en otras fronteras
    for bnode, zid in boundaries.items():
        if bnode not in fg.idx:
            continue
        q = deque([bnode])
        node_to_zone[bnode] = zid
        zone_members[zid].append(bnode)
        while q:
            cur = q.popleft()
            for ci in fg.g.successor_indices(fg.idx[cur]):
                child = fg.name[ci]
                if child in boundaries and child != bnode:
                    continue  # inicia otra zona
                if child in node_to_zone:
                    continue
                node_to_zone[child] = zid
                zone_members[zid].append(child)
                q.append(child)

    # zona padre de cada zona (dispositivo aguas arriba)
    parent_zone: dict[str, str | None] = {}
    for bnode, zid in boundaries.items():
        up = fg.parent.get(bnode)
        pz = None
        while up is not None:
            if up in boundaries:
                pz = boundaries[up]
                break
            up = fg.parent.get(up)
        parent_zone[zid] = pz

    site_nodes = set()
    if sites is not None:
        site_nodes = set(sites["node_id"].tolist())

    rows = []
    for zid, members in zone_members.items():
        mset = set(members)
        n_cust = sum(1 for n in members if "-C" in n)
        n_tx = len(mset & site_nodes)
        rows.append({
            "feeder_id": fg.feeder_id, "zone_id": zid,
            "parent_zone": parent_zone.get(zid),
            "n_nodes": len(members), "n_customers": n_cust,
            "n_tx_sites": n_tx,
            "has_upstream_device": parent_zone.get(zid) is not None or zid == "HEAD",
        })
    zones = pd.DataFrame(rows).sort_values("zone_id").reset_index(drop=True)
    return zones, node_to_zone
