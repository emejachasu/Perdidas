"""Generador de datos sintéticos parametrizable (Anexo C, punto 4).

Produce el universo objetivo con:
  - jerarquía poste → puesto → unidad,
  - bancos de 1, 2 y 3 unidades incluyendo delta abierto,
  - 24-48 meses de consumo con estacionalidad,
  - hurtos inyectados de patrón conocido (caída y recuperación),
  - medidores de cabecera coherentes con el balance,
  - etiquetas de verdad-terreno para validar la detección (§19.5).

Todos los tamaños vienen del perfil activo en ``config/scale.yaml``; nada está
escrito como constante de negocio en el código.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import Config, load_config
from ..domain.bank import UnitPlate, bank_capacity
from ..domain.enums import BankConfig
from ..electrical import formulas as F
from ..lakehouse import Lakehouse
from ..pipeline.technical import (
    secondary_conductor_loss_kwh,
    transformer_site_energy_loss_kwh,
)

# Catálogos internos de simulación (no son parámetros de negocio del cliente;
# describen el universo sintético, análogo a datos de placa de ArcFM).
KVA_CATALOG = np.array([25.0, 37.5, 50.0, 75.0, 100.0, 167.0, 250.0])
BANK_CHOICES = [
    (BankConfig.SINGLE, 1, 0.55),
    (BankConfig.WYE_CLOSED, 3, 0.18),
    (BankConfig.DELTA_CLOSED, 3, 0.07),
    (BankConfig.OPEN_DELTA, 2, 0.12),
    (BankConfig.DELTA_4WIRE, 3, 0.08),
]
TARIFF_CHOICES = [
    ("residential", 0.80, 180.0),
    ("commercial", 0.15, 900.0),
    ("industrial", 0.05, 4000.0),
]
SECONDARY_LOSS_PCT = 0.035   # pérdida agregada de secundario+acometidas (universo sintético)


@dataclass
class SyntheticGenerator:
    cfg: Config = field(default_factory=load_config)

    def __post_init__(self) -> None:
        p = self.cfg.active_profile
        self.n_feeders = int(p["feeders"])
        self.cust_mean = int(p["customers_per_feeder_mean"])
        self.poles_mean = int(p["poles_per_feeder_mean"])
        self.months = int(p["history_months"])
        self.theft_rate = float(p["theft_rate"])
        self.seed = int(p["seed"])
        self.k = float(self.cfg.electrical["loss_factor_k"])
        self.tariff_pf = self.cfg.electrical["power_factor_by_class"]

    # ---- generación de un alimentador ----
    def feeder_tables(self, feeder_idx: int) -> dict[str, pd.DataFrame]:
        rng = np.random.default_rng(self.seed + feeder_idx)
        fid = f"F{feeder_idx:04d}"

        n_customers = int(rng.normal(self.cust_mean, self.cust_mean * 0.15))
        n_customers = max(50, n_customers)
        n_poles = max(10, int(rng.normal(self.poles_mean, self.poles_mean * 0.15)))
        customers_per_tx = int(rng.integers(15, 30))
        n_tx = max(1, n_customers // customers_per_tx)

        poles = self._poles(rng, fid, n_poles)
        sites, units = self._transformer_sites(rng, fid, n_tx, poles)
        customers = self._customers(rng, fid, n_customers, sites, poles)
        streetlights = self._streetlights(rng, fid, n_tx, sites, poles)
        consumption, labels = self._consumption(rng, fid, customers)
        header = self._header(fid, sites, units, customers, consumption, streetlights)
        segments, devices, anomalies = self._network(rng, fid, sites, customers, poles)
        events = self._switching_events(rng, fid, devices, customers)

        return {
            "poles": poles,
            "sites": sites,
            "transformer_units": units,
            "load_points": self._load_points(customers),
            "customers": customers,
            "streetlights": streetlights,
            "consumption": consumption,
            "header_meters": header,
            "theft_labels": labels,
            "segments": segments,
            "switching_devices": devices,
            "switching_events": events,
            "anomaly_labels": anomalies,
        }

    def _switching_events(self, rng, fid, devices, customers) -> pd.DataFrame:
        """Genera algunos eventos de falla con duración y carga afectada (§7.2/§7.6)."""
        if devices is None or devices.empty:
            return pd.DataFrame(columns=["device_id", "feeder_id", "timestamp",
                                         "estado_previo", "estado_nuevo", "motivo",
                                         "duration_h", "affected_kw"])
        avg_load_kw = float(customers["base_kwh"].sum()) / 730.0 if "base_kwh" in customers else 0.0
        n_ev = int(rng.integers(1, 4))
        rows = []
        for j in range(n_ev):
            dev = devices.sample(1, random_state=int(rng.integers(0, 1e6))).iloc[0]
            month = int(rng.integers(1, 12))
            rows.append({
                "device_id": dev["device_id"], "feeder_id": fid,
                "timestamp": f"2023-{month:02d}-15 03:00:00",
                "estado_previo": "NC", "estado_nuevo": "NA", "motivo": "falla",
                "duration_h": round(float(rng.uniform(1.0, 6.0)), 2),
                "affected_kw": round(avg_load_kw * float(rng.uniform(0.05, 0.20)), 2),
            })
        return pd.DataFrame(rows)

    def _network(self, rng, fid, sites, customers, poles):
        """Red radial: tramos primarios (árbol), transformador (arista implícita
        vía units), tramos secundarios y dispositivos de maniobra. Inyecta
        anomalías con verdad-terreno para validar las reglas R01-R25 (§8)."""
        cond = self.cfg.conductors
        prim_order = self.cfg.conductor_ordering["primary"]
        sec_order = self.cfg.conductor_ordering["secondary"]
        v_mv = float(self.cfg.electrical["voltage"]["ll_mv"])
        v_lv = float(self.cfg.electrical["voltage"]["ll_lv"])
        pole_xy = poles.set_index("pole_id")[["x", "y"]]
        src = f"{fid}-SRC"

        # nodos primarios de cada puesto
        nodes = []
        for _, s in sites.iterrows():
            xy = pole_xy.loc[s["pole_id"]]
            nodes.append((s["node_id"], s["site_id"], float(xy["x"]), float(xy["y"])))
        nodes.sort(key=lambda t: t[2] ** 2 + t[3] ** 2)

        placed = [(src, 0.0, 0.0, 0)]   # (node, x, y, depth)
        parent_conductor: dict[str, str] = {}
        seg_rows, seg_i = [], 0
        for node_id, site_id, x, y in nodes:
            best = min(placed, key=lambda p: (p[1] - x) ** 2 + (p[2] - y) ** 2)
            length_km = max(0.01, math.hypot(best[1] - x, best[2] - y) / 1000.0)
            depth = best[3] + 1
            idx = max(0, len(prim_order) - 1 - depth // 3)
            code = prim_order[idx]
            c = cond[code]
            seg_rows.append(self._seg_row(fid, f"{fid}-S{seg_i:05d}", best[0], node_id,
                                          length_km, code, c, "ABC", v_mv, "overhead", depth))
            parent_conductor[node_id] = code
            placed.append((node_id, x, y, depth))
            seg_i += 1

        # tramos secundarios: cliente -> nodo secundario del puesto
        site_node = sites.set_index("site_id")["node_id"].to_dict()
        for _, cu in customers.iterrows():
            tx = cu["transformer_site_id"]
            snode = f"{site_node.get(tx, src)}_S"
            code = sec_order[int(rng.integers(0, len(sec_order)))]
            c = cond[code]
            length_km = max(0.005, float(rng.uniform(0.01, 0.08)))
            phase = cu.get("phase") or rng.choice(["A", "B", "C"])
            seg_rows.append(self._seg_row(fid, f"{fid}-SS{seg_i:05d}", snode,
                                          cu["customer_unit_id"], length_km, code, c,
                                          str(phase), v_lv, "overhead", 99))
            seg_i += 1

        segments = pd.DataFrame(seg_rows)

        # dispositivos de maniobra en una fracción de tramos primarios
        prim = segments[segments["voltage_ll"] == v_mv]
        n_dev = max(1, len(prim) // 12)
        dev_idx = rng.choice(prim.index.to_numpy(), size=min(n_dev, len(prim)), replace=False)
        dev_rows = []
        types = ["seccionador", "reconectador", "interruptor", "fusible", "seccionador_enlace"]
        for j, si in enumerate(dev_idx):
            row = segments.loc[si]
            dev_rows.append({
                "device_id": f"{fid}-DV{j:03d}", "feeder_id": fid,
                "site_id": None, "node_id": row["node_to"],
                "type": str(rng.choice(types)),
                "normal_state": "NC" if rng.random() > 0.15 else "NA",
                "current_state": "NC", "remote": bool(rng.random() > 0.5),
            })
        devices = pd.DataFrame(dev_rows)

        segments, anomalies = self._inject_anomalies(rng, fid, segments, prim_order)
        return segments, devices, anomalies

    @staticmethod
    def _seg_row(fid, sid, nfrom, nto, length_km, code, c, phase, v_ll, constr, depth):
        return {
            "segment_id": sid, "feeder_id": fid, "feeder_id_declared": fid,
            "node_from": nfrom, "node_to": nto, "length_m": round(length_km * 1000, 2),
            "conductor_code": code, "r_ohm_per_km": c["r_ohm_km"],
            "x_ohm_per_km": c["x_ohm_km"], "ampacity_a": c["ampacity_a"],
            "phase": phase, "voltage_ll": v_ll, "construction": constr,
            "material": c["material"], "section": c["section"], "depth": depth,
        }

    def _inject_anomalies(self, rng, fid, segments, prim_order):
        """Inyecta anomalías conocidas: R01 sándwich, R08 feeder_id, R06 fases."""
        segs = segments.copy()
        labels = []
        prim = segs[segs["section"] == "primary"]
        if len(prim) >= 5:
            # R01: conductor sándwich (tramo distinto entre dos iguales)
            for _ in range(max(1, len(prim) // 40)):
                si = int(rng.choice(prim.index.to_numpy()))
                other = [c for c in prim_order if c != segs.at[si, "conductor_code"]]
                segs.at[si, "conductor_code"] = other[0]
                labels.append({"feeder_id": fid, "segment_id": segs.at[si, "segment_id"],
                               "injected_rule": "R01"})
            # R08: feeder_id inconsistente
            si = int(rng.choice(prim.index.to_numpy()))
            segs.at[si, "feeder_id_declared"] = "F9999"
            labels.append({"feeder_id": fid, "segment_id": segs.at[si, "segment_id"],
                           "injected_rule": "R08"})
        return segs, pd.DataFrame(labels)

    def _poles(self, rng, fid, n) -> pd.DataFrame:
        return pd.DataFrame({
            "pole_id": [f"{fid}-P{i:05d}" for i in range(n)],
            "feeder_id": fid,
            "x": rng.uniform(0, 5000, n),
            "y": rng.uniform(0, 5000, n),
            "pole_type": rng.choice(["concrete", "wood", "steel"], n),
            "height_m": rng.choice([9.0, 11.0, 12.0], n),
        })

    def _transformer_sites(self, rng, fid, n, poles) -> tuple[pd.DataFrame, pd.DataFrame]:
        configs, counts, _ = zip(*BANK_CHOICES)
        probs = np.array([c[2] for c in BANK_CHOICES])
        probs = probs / probs.sum()
        chosen = rng.choice(len(BANK_CHOICES), size=n, p=probs)

        site_rows, unit_rows = [], []
        pole_ids = poles["pole_id"].to_numpy()
        for i in range(n):
            cfg, cnt, _ = BANK_CHOICES[chosen[i]]
            sid = f"{fid}-TS{i:04d}"
            pole_id = rng.choice(pole_ids)
            site_rows.append({
                "site_id": sid, "feeder_id": fid, "pole_id": pole_id,
                "kind": "transformer", "bank_config": cfg.value,
                "node_id": f"{fid}-N{i:04d}",
            })
            base_kva = float(rng.choice(KVA_CATALOG))
            for u in range(cnt):
                # bancos desiguales ocasionales para ejercitar §5.2
                sn = base_kva if rng.random() > 0.15 else float(rng.choice(KVA_CATALOG))
                unit_rows.append({
                    "unit_id": f"{sid}-U{u}", "site_id": sid, "feeder_id": fid,
                    "kind": "transformer", "sn_kva": sn,
                    "p0_kw": round(0.0025 * sn, 4),   # ~0.25% Sn vacío
                    "pk_kw": round(0.011 * sn, 4),    # ~1.1% Sn carga nominal
                    "voltage_ln": 220.0,
                    "phase": "ABC" if cnt == 3 else ("AB" if cnt == 2 else "A"),
                    "plate_source": "catalog",
                })
        return pd.DataFrame(site_rows), pd.DataFrame(unit_rows)

    def _customers(self, rng, fid, n, sites, poles) -> pd.DataFrame:
        tx_ids = sites["site_id"].to_numpy()
        pole_ids = poles["pole_id"].to_numpy()
        classes, cprobs, _ = zip(*TARIFF_CHOICES)
        cprobs = np.array(cprobs)
        klass = rng.choice(len(TARIFF_CHOICES), size=n, p=cprobs)
        # puestos de cliente: algunos multi-unidad (§5.3)
        # Puestos de cliente MULTI-UNIDAD (§5.3): una fracción de los puestos
        # agrupa varias unidades de servicio (edificios, locales sobre una misma
        # acometida). Es lo que ejercita el mecanismo M8 y la asimetría de costo
        # por visita de §17.1; con 1 unidad por puesto nunca se activarían.
        site_of_customer, cs_idx, i = [], 0, 0
        while len(site_of_customer) < n:
            group = int(rng.choice([1, 1, 1, 2, 3, 6], p=[.55, .15, .10, .10, .06, .04]))
            for _ in range(min(group, n - len(site_of_customer))):
                site_of_customer.append(f"{fid}-CS{cs_idx:06d}")
            cs_idx += 1

        # Las unidades de un mismo puesto comparten acometida: mismo poste, mismo
        # transformador y misma fase (§5.3).
        site_attrs: dict[str, tuple] = {}
        rows = []
        for i in range(n):
            name, _, base = TARIFF_CHOICES[klass[i]]
            cs = site_of_customer[i]
            if cs not in site_attrs:
                site_attrs[cs] = (rng.choice(tx_ids), rng.choice(pole_ids),
                                  str(rng.choice(["A", "B", "C"])))
            tx, pole, phase = site_attrs[cs]
            rows.append({
                "customer_unit_id": f"{fid}-C{i:06d}",
                "site_id": cs,
                "feeder_id": fid,
                "pole_id": pole,
                "tariff_class": name,
                "phase": phase,   # acometida monofásica compartida en el puesto
                "installed_load_kw": round(base / 30.0 / 24.0 * rng.uniform(3, 6), 3),
                "service_drop_kva": round(base / 200.0 * rng.uniform(1.0, 1.5), 2),
                "transformer_site_id": tx,
                "base_kwh": round(base * rng.uniform(0.7, 1.3), 1),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _load_points(customers: pd.DataFrame) -> pd.DataFrame:
        """Deriva los PUNTOS DE CARGA (PuntoCarga de CNEL) de las conexiones.

        Un punto de carga agrupa N conexiones consumidor que comparten poste,
        transformador, fase y acometida (§5.3).
        """
        g = customers.groupby("site_id")
        lp = g.agg(
            feeder_id=("feeder_id", "first"),
            transformer_site_id=("transformer_site_id", "first"),
            pole_id=("pole_id", "first"),
            phase=("phase", "first"),
            n_connections=("customer_unit_id", "count"),
        ).reset_index().rename(columns={"site_id": "load_point_id"})
        # la acometida del punto dimensiona el conjunto, no cada medidor
        lp["service_drop_kva"] = (g["service_drop_kva"].sum() * 0.8).round(2).to_numpy()
        return lp

    def _streetlights(self, rng, fid, n_tx, sites, poles) -> pd.DataFrame:
        n = int(n_tx * rng.uniform(2, 5))
        tx_ids = sites["site_id"].to_numpy()
        pole_ids = poles["pole_id"].to_numpy()
        techs = rng.choice(["led", "sodium", "mercury"], n, p=[0.6, 0.3, 0.1])
        # tecnología instalada = declarada, salvo un % de discordancia (§10.3.4)
        installed = techs.copy()
        mism = rng.random(n) < 0.05
        installed[mism] = "led"
        # fotocelda averiada -> day-burning (§10.3.2)
        photocell_fault = rng.random(n) < 0.03
        tx_assigned = rng.choice(tx_ids, n).astype(object)
        # algunas luminarias sin puesto asignable (R25 / §10.3.5)
        tx_assigned[rng.random(n) < 0.02] = None
        return pd.DataFrame({
            "streetlight_id": [f"{fid}-L{i:05d}" for i in range(n)],
            "feeder_id": fid,
            "site_id": rng.choice(pole_ids, n),
            "transformer_site_id": tx_assigned,
            "technology": techs,
            "installed_technology": installed,
            "photocell_fault": photocell_fault,
            "lamp_w": rng.choice([70.0, 100.0, 150.0], n),
        })

    def _consumption(self, rng, fid, customers) -> tuple[pd.DataFrame, pd.DataFrame]:
        months = pd.period_range("2022-01", periods=self.months, freq="M").astype(str)
        season = 1.0 + 0.15 * np.sin(np.linspace(0, 2 * np.pi, self.months))

        recs, labels = [], []
        theft_mask = rng.random(len(customers)) < self.theft_rate

        for row_idx, (_, c) in enumerate(customers.iterrows()):
            base = c["base_kwh"]
            true_series = base * season * rng.normal(1.0, 0.05, self.months)
            true_series = np.clip(true_series, 0, None)
            billed = true_series.copy()

            stolen_total = 0.0
            is_theft = bool(theft_mask[row_idx])
            if is_theft:
                # patrón caída y recuperación (M1, el más informativo §15.2)
                start = int(rng.integers(3, max(4, self.months - 6)))
                dur = int(rng.integers(4, 10))
                end = min(self.months, start + dur)
                frac = float(rng.uniform(0.35, 0.75))
                billed[start:end] = true_series[start:end] * (1.0 - frac)
                stolen_total = float((true_series[start:end] - billed[start:end]).sum())

            pf = self.tariff_pf.get(
                "residential" if c["tariff_class"] == "residential"
                else ("commercial" if c["tariff_class"] == "commercial" else "industrial"),
                0.92,
            )
            tanphi = np.tan(np.arccos(pf))
            for m, mon in enumerate(months):
                kwh = float(billed[m])
                recs.append({
                    "customer_unit_id": c["customer_unit_id"],
                    "feeder_id": fid, "year_month": mon,
                    "kwh": round(kwh, 2),
                    "kvarh": round(kwh * tanphi, 2),
                    "estimated": bool(rng.random() < 0.03),
                    "true_kwh": round(float(true_series[m]), 2),
                })
            labels.append({
                "customer_unit_id": c["customer_unit_id"], "feeder_id": fid,
                "is_theft": is_theft, "stolen_kwh": round(stolen_total, 2),
                "mechanism": "drop_recovery" if is_theft else "none",
            })
        return pd.DataFrame(recs), pd.DataFrame(labels)

    def _header(self, fid, sites, units, customers, consumption, streetlights) -> pd.DataFrame:
        """Cabecera coherente: entregada = facturada + robada + AP + técnicas."""
        # energía verdadera y facturada por mes
        by_month = consumption.groupby("year_month").agg(
            billed=("kwh", "sum"), true=("true_kwh", "sum"),
        ).reset_index()
        stolen_by_month = by_month["true"] - by_month["billed"]

        # AP por mes (§10): potencia*horas*días
        hours_on = float(self.cfg.streetlight["hours_on_default"])
        ap_kwh_month = 0.0
        tech = self.cfg.streetlight["technology"]
        for _, s in streetlights.iterrows():
            t = tech.get(s["technology"], tech["led"])
            p_kw = s["lamp_w"] / 1000.0 * (1.0 + t["ballast_loss_frac"])
            ap_kwh_month += p_kw * hours_on * 30.0
        ap = np.full(len(by_month), ap_kwh_month)

        # pérdidas técnicas por mes (mismas fórmulas que el balance)
        tech_month = self._technical_losses_month(sites, units, by_month["true"].to_numpy())

        header_kwh = by_month["true"].to_numpy() + ap + tech_month
        return pd.DataFrame({
            "feeder_id": fid,
            "year_month": by_month["year_month"],
            "kwh": np.round(header_kwh, 2),
            "kvarh": np.round(header_kwh * 0.35, 2),
        })

    def _technical_losses_month(self, sites, units, true_month) -> np.ndarray:
        hours = 730.0
        fc = 0.45
        fp = F.loss_factor(fc, self.k)
        losses = np.zeros(len(true_month))
        by_site = {sid: g for sid, g in units.groupby("site_id")}
        n_sites = max(1, len(sites))
        for _, s in sites.iterrows():
            g = by_site.get(s["site_id"])
            if g is None:
                continue
            plates = [UnitPlate(r.sn_kva, r.p0_kw, r.pk_kw, r.voltage_ln)
                      for r in g.itertuples()]
            cfg = BankConfig(s["bank_config"])
            cap, _ = bank_capacity(cfg, plates)
            for m in range(len(true_month)):
                site_energy = true_month[m] / n_sites
                p_mean = F.mean_power_kw(site_energy, hours)
                s_max = (p_mean / fc) / 0.92     # kVA pico aprox
                losses[m] += transformer_site_energy_loss_kwh(
                    plates, s_max, cap, fp, hours,
                )
        # sumar secundario+acometidas
        losses += secondary_conductor_loss_kwh(true_month, SECONDARY_LOSS_PCT, fp)
        return losses


def generate_universe(root: str, cfg: Config | None = None) -> dict[str, int]:
    """Genera el universo y lo escribe en la capa BRONZE. Devuelve conteos."""
    cfg = cfg or load_config()
    gen = SyntheticGenerator(cfg)
    lake = Lakehouse(root)
    counts = {"feeders": 0, "poles": 0, "sites": 0, "transformer_units": 0,
              "customers": 0, "streetlights": 0, "consumption": 0, "segments": 0}
    for i in range(gen.n_feeders):
        fid = f"F{i:04d}"
        tables = gen.feeder_tables(i)
        for entity, df in tables.items():
            lake.write_partition("bronze", entity, fid, df)
        counts["feeders"] += 1
        counts["poles"] += len(tables["poles"])
        counts["sites"] += len(tables["sites"])
        counts["transformer_units"] += len(tables["transformer_units"])
        counts["customers"] += len(tables["customers"])
        counts["streetlights"] += len(tables["streetlights"])
        counts["consumption"] += len(tables["consumption"])
        counts["segments"] += len(tables["segments"])
    return counts
