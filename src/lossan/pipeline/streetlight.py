"""Alumbrado público: horas por efemérides y anomalías (§10).

- ``compute_hours_on``: horas de encendido por latitud y mes con efemérides
  (astral), en vez del valor fijo de 11,5 h.
- ``detect_ap_anomalies``: day-burning por fotocelda averiada, tecnología
  declarada ≠ instalada, y luminaria sin puesto asignable (§10.3).
"""
from __future__ import annotations

import calendar

import pandas as pd

from ..config import Config, load_config


def compute_hours_on(latitude: float, month: int, year: int = 2024) -> float:
    """Horas medias de oscuridad (encendido de AP con fotocelda) del mes."""
    try:
        from astral import LocationInfo
        from astral.sun import sun
        import datetime as _dt

        loc = LocationInfo(latitude=latitude, longitude=0.0)
        days = calendar.monthrange(year, month)[1]
        total = 0.0
        for d in range(1, days + 1):
            try:
                s = sun(loc.observer, date=_dt.date(year, month, d))
                night = 24.0 - (s["sunset"] - s["sunrise"]).total_seconds() / 3600.0
                total += night
            except Exception:
                total += 11.5
        return round(total / days, 3)
    except Exception:
        return 11.5


def annual_hours_on(latitude: float, cfg: Config | None = None) -> float:
    """Horas medias diarias de encendido en el año (efemérides o default)."""
    cfg = cfg or load_config()
    if not cfg.streetlight.get("use_ephemeris", False):
        return float(cfg.streetlight["hours_on_default"])
    return round(sum(compute_hours_on(latitude, m) for m in range(1, 13)) / 12.0, 3)


def detect_ap_anomalies(streetlights: pd.DataFrame, feeder_id: str,
                        cfg: Config | None = None) -> pd.DataFrame:
    """Detecta anomalías de alumbrado público (§10.3)."""
    if streetlights is None or streetlights.empty:
        return pd.DataFrame(columns=["feeder_id", "streetlight_id", "anomaly",
                                     "severity", "evidence"])
    rows = []
    for r in streetlights.itertuples():
        sid = r.streetlight_id
        # tecnología declarada != instalada
        inst = getattr(r, "installed_technology", None)
        if inst is not None and inst != r.technology:
            rows.append((feeder_id, sid, "tech_mismatch", "alta",
                         f"declarada {r.technology} != instalada {inst}"))
        # day-burning por fotocelda averiada (consumo 24 h)
        if bool(getattr(r, "photocell_fault", False)):
            rows.append((feeder_id, sid, "day_burning", "media",
                         "fotocelda averiada: consumo 24 h"))
        # luminaria sin puesto de transformación asignable
        tx = getattr(r, "transformer_site_id", None)
        if tx is None or (isinstance(tx, float)) or tx == "" or pd.isna(tx):
            rows.append((feeder_id, sid, "no_transformer_site", "media",
                         "sin puesto de transformación por traza (R25)"))
    return pd.DataFrame(rows, columns=["feeder_id", "streetlight_id", "anomaly",
                                       "severity", "evidence"])
