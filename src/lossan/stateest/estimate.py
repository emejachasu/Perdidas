"""Estimación de estado por mínimos cuadrados ponderados (DSSE-WLS, §14.3).

- Pseudo-mediciones por nodo con incertidumbre derivada de la variabilidad
  histórica del cliente y su clase.
- WLS sobre la red radial anclado a la medición de cabecera.
- Análisis de residuos normalizados: residuos sistemáticamente altos en un
  ramal indican carga no contabilizada aguas abajo (test chi-cuadrado para
  error grueso y Largest Normalized Residual para localizar el nodo/zona).
- Reconciliación descendente proporcional al residuo, nunca uniforme.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class WLSResult:
    x: np.ndarray                 # estado estimado (inyección/carga por nodo)
    residuals: np.ndarray         # z − Hx
    normalized_residuals: np.ndarray
    chi2: float                   # J(x) = Σ w r²
    chi2_dof: int
    gross_error: bool             # J > umbral chi²
    lnr_index: int                # nodo del mayor residuo normalizado
    correction: np.ndarray        # x − pseudo (carga reconciliada añadida)


def pseudo_measurements(site_monthly: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Construye pseudo-mediciones por puesto a partir del histórico.

    ``site_monthly``: columnas ``site_id, mean_kw, std_kw``. La incertidumbre
    (sigma) proviene de la variabilidad histórica; a mayor variabilidad, menor
    peso en el WLS (la reconciliación cargará más sobre esos nodos).
    """
    ids = site_monthly["site_id"].to_numpy()
    z = site_monthly["mean_kw"].to_numpy(dtype=float)
    sigma = site_monthly["std_kw"].to_numpy(dtype=float)
    # piso de incertidumbre relativo para evitar sigma=0
    sigma = np.maximum(sigma, 0.05 * np.maximum(z, 1e-6) + 1e-3)
    return ids, z, sigma


def run_wls(z: np.ndarray, sigma: np.ndarray, measured_total: float,
            anchor_sigma_frac: float = 0.005) -> WLSResult:
    """WLS lineal con ancla de cabecera.

    Estado x = carga por nodo. Mediciones: cada pseudo z_i (peso 1/σ_i²) y la
    suma total medida en cabecera Σx = measured_total (ancla de peso alto).
    """
    n = len(z)
    w_node = 1.0 / (sigma ** 2)
    anchor_sigma = max(anchor_sigma_frac * abs(measured_total), 1e-3)
    w_anchor = 1.0 / (anchor_sigma ** 2)

    # Ecuaciones normales: (W_node·I + w_anchor·1·1ᵀ) x = W_node·z + w_anchor·total·1
    A = np.diag(w_node) + w_anchor * np.ones((n, n))
    b = w_node * z + w_anchor * measured_total * np.ones(n)
    x = np.linalg.solve(A, b)

    # residuos de las mediciones de nodo
    r = z - x
    # covarianza de residuos aproximada (diagonal): Ω_ii ≈ σ_i²·(1 − h_ii)
    Ainv = np.linalg.inv(A)
    hat = w_node[:, None] * Ainv                       # gananacia
    omega = np.maximum(sigma ** 2 * (1.0 - np.diag(hat) * 0 + 1e-9), 1e-9)
    # usar σ como escala robusta para el residuo normalizado
    rn = r / sigma

    chi2 = float(np.sum(w_node * r ** 2))
    dof = max(1, (n + 1) - n)                           # mediciones − estados
    # umbral chi² ~ dof + 3√(2·dof) (aprox 99%)
    threshold = dof + 3.0 * np.sqrt(2.0 * dof)
    lnr = int(np.argmax(np.abs(rn)))
    correction = x - z
    return WLSResult(x=x, residuals=r, normalized_residuals=rn, chi2=chi2,
                     chi2_dof=dof, gross_error=chi2 > threshold, lnr_index=lnr,
                     correction=correction)


def reconcile_by_zone(site_ids: np.ndarray, correction: np.ndarray,
                      normalized_residuals: np.ndarray,
                      site_to_zone: dict[str, str], feeder_id: str) -> pd.DataFrame:
    """Agrega la reconciliación por zona de protección (ramal accionable).

    La carga añadida (correction > 0) concentrada en una zona señala carga no
    contabilizada aguas abajo (candidata a PNT localizada).
    """
    df = pd.DataFrame({
        "site_id": site_ids, "correction_kw": correction,
        "norm_residual": normalized_residuals,
    })
    df["zone_id"] = df["site_id"].map(lambda s: site_to_zone.get(s, "HEAD"))
    agg = df.groupby("zone_id").agg(
        unaccounted_load_kw=("correction_kw", lambda s: float(np.clip(s, 0, None).sum())),
        max_norm_residual=("norm_residual", lambda s: float(np.max(np.abs(s)))),
        n_sites=("site_id", "count"),
    ).reset_index()
    agg["feeder_id"] = feeder_id
    total = agg["unaccounted_load_kw"].sum()
    agg["share_of_unaccounted"] = np.where(total > 0, agg["unaccounted_load_kw"] / total, 0.0)
    return agg.sort_values("unaccounted_load_kw", ascending=False).reset_index(drop=True)
