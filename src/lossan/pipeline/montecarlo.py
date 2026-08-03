"""Monte Carlo de incertidumbre de pérdidas (§12).

Propaga la incertidumbre de los atributos (índice M2), de P0/Pk estimados vs.
placa y de las curvas de carga, para reportar **P10/P50/P90** de las pérdidas
técnicas y, por diferencia, de la PNT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config, load_config


def monte_carlo_feeder(base_technical_kwh: float, losses_total_kwh: float,
                       cfg: Config | None = None) -> dict:
    """Distribución de pérdidas técnicas y PNT por Monte Carlo (lognormal)."""
    cfg = cfg or load_config()
    mc = cfg.thresholds["montecarlo"]
    n = int(mc["n_samples"])
    sigma = float(mc["sigma_technical"])
    rng = np.random.default_rng(int(mc["seed"]))
    # factor lognormal de media 1 y desviación relativa ~ sigma
    mu = -0.5 * np.log(1 + sigma ** 2)
    s = np.sqrt(np.log(1 + sigma ** 2))
    factors = rng.lognormal(mu, s, n)
    tech = base_technical_kwh * factors
    pnt = losses_total_kwh - tech
    q = lambda a, p: float(np.percentile(a, p))
    return {
        "technical_p10": round(q(tech, 10), 1), "technical_p50": round(q(tech, 50), 1),
        "technical_p90": round(q(tech, 90), 1),
        "pnt_p10": round(q(pnt, 10), 1), "pnt_p50": round(q(pnt, 50), 1),
        "pnt_p90": round(q(pnt, 90), 1),
        "n_samples": n, "sigma_technical": sigma,
    }


def monte_carlo_table(feeder_id: str, base_technical_kwh: float,
                      losses_total_kwh: float, cfg: Config | None = None) -> pd.DataFrame:
    """Fila GOLD de incertidumbre para un alimentador."""
    d = monte_carlo_feeder(base_technical_kwh, losses_total_kwh, cfg)
    d["feeder_id"] = feeder_id
    return pd.DataFrame([d])
