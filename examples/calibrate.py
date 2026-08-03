"""Ejemplo de calibración del modelo de riesgo de hurto.

Usa el lakehouse (datos sintéticos o reales) para:
  1. Validar la minería de etiquetas contra la verdad-terreno (recall, §22.8).
  2. Comparar los métodos de PU learning por Precision@k y energía@k (§17.2).
  3. Barrer un umbral de minería y ver su efecto en recall/precisión.

Es una PLANTILLA: adáptala a tu red. Con datos reales, sustituye
``theft_labels`` por tus hurtos confirmados (tabla con is_theft / stolen_kwh).

Uso:
    python examples/calibrate.py --root data/lake --feeder F0000
    python examples/calibrate.py --root data/lake --all
"""
from __future__ import annotations

import argparse
import warnings

import pandas as pd

from lossan.config import load_config
from lossan.lakehouse import Lakehouse
from lossan.ml import (mine_labels, train_risk_model, precision_at_k,
                       energy_recoverable_at_k, validate_against_confirmed)
from lossan.ml.pu import PU_METHODS

warnings.filterwarnings("ignore")
pd.set_option("display.width", 120)


def load_data(root: str, feeder: str | None):
    lake = Lakehouse(root)
    cons = lake.read_entity("bronze", "consumption", feeder)
    cust = lake.read_entity("bronze", "customers", feeder)
    labels = lake.read_entity("bronze", "theft_labels", feeder)
    if cons.empty or cust.empty:
        raise SystemExit("No hay datos. Ejecuta 'lossan generate' o ingiere tu red/consumo.")
    return cons, cust, labels


def budget_k_values(cfg) -> list[int]:
    budget = float(cfg.budget["field_usd"])
    ks = []
    for cpv in (20, 30, 50, 80):
        ks.append(int(budget / cpv))
    return ks


def report_label_mining(cons, cust, labels, cfg):
    print("\n" + "=" * 70)
    print("1) MINERÍA DE ETIQUETAS vs. VERDAD-TERRENO (criterio §22.8)")
    print("=" * 70)
    mined = mine_labels(cons, cust, cfg)
    if not mined.empty:
        print("Etiquetas minadas por mecanismo:")
        print(mined["label_source"].value_counts().to_string())
    if not labels.empty and labels["is_theft"].any():
        val = validate_against_confirmed(mined, labels)
        print(f"\n  Hurtos confirmados        : {val['confirmed']}")
        print(f"  Recall (todos los mec.)   : {val['recall_all']:.1%}")
        print(f"  Recall (M1+M2 alta conf.) : {val['recall_high_conf']:.1%}")
        print(f"  Precisión minado vs conf. : {val['precision_all_vs_confirmed']:.1%}")
    else:
        print("  (Sin verdad-terreno: usa tus hurtos confirmados reales aquí.)")


def report_pu_comparison(cons, cust, labels, cfg):
    print("\n" + "=" * 70)
    print("2) COMPARACIÓN DE MÉTODOS PU — Precision@k y energía@k (§17.2)")
    print("=" * 70)
    if labels.empty or not labels["is_theft"].any():
        print("  Sin verdad-terreno para evaluar Precision@k.")
        return
    truth = set(labels.loc[labels["is_theft"], "customer_unit_id"])
    n = cust.shape[0]
    ks = [k for k in (20, 50, 100, 200) if k <= n]
    rows = []
    for method in PU_METHODS:
        scores, info = train_risk_model(cons, cust, labels, method=method, cfg=cfg)
        row = {"metodo": method}
        for k in ks:
            row[f"P@{k}"] = precision_at_k(scores, truth, k)
        row["energia@%d(kWh/mes)" % ks[-1]] = energy_recoverable_at_k(scores, truth, ks[-1])
        rows.append(row)
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    best = df.loc[df[f"P@{ks[0]}"].idxmax(), "metodo"]
    print(f"\n  → Mejor método en la cabeza del ranking (P@{ks[0]}): {best}")
    print("    Ajusta el método en train_risk_model(..., method=...) o en el pipeline.")


def report_threshold_sweep(cons, cust, labels, cfg):
    print("\n" + "=" * 70)
    print("3) BARRIDO DE UMBRAL — drop_recovery_pct (mecanismo M1)")
    print("=" * 70)
    if labels.empty or not labels["is_theft"].any():
        print("  Sin verdad-terreno para el barrido.")
        return
    rows = []
    original = cfg.thresholds["label_mining"]["drop_recovery_pct"]
    for thr in (0.25, 0.35, 0.45, 0.55):
        cfg.thresholds["label_mining"]["drop_recovery_pct"] = thr
        mined = mine_labels(cons, cust, cfg)
        val = validate_against_confirmed(mined, labels)
        rows.append({"drop_recovery_pct": thr,
                     "minadas_total": val["mined_total"],
                     "recall_all": val["recall_all"],
                     "precision_vs_conf": val["precision_all_vs_confirmed"]})
    cfg.thresholds["label_mining"]["drop_recovery_pct"] = original
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n  → Sube el umbral si hay muchos falsos positivos; bájalo si el recall es bajo.")
    print("    Fija el elegido en config/thresholds.yaml: label_mining.drop_recovery_pct")


def main():
    ap = argparse.ArgumentParser(description="Calibración del modelo de riesgo.")
    ap.add_argument("--root", default="data/lake", help="Raíz del lakehouse.")
    ap.add_argument("--feeder", default=None, help="Alimentador (ej. F0000).")
    ap.add_argument("--all", action="store_true", help="Usar todos los alimentadores.")
    args = ap.parse_args()

    cfg = load_config()
    feeder = None if args.all else (args.feeder or "F0000")
    cons, cust, labels = load_data(args.root, feeder)

    print(f"Dataset: {cust.shape[0]} clientes · {cons['year_month'].nunique()} meses"
          + (f" · alimentador {feeder}" if feeder else " · todos"))
    print(f"k derivados del presupuesto (§17.2): {budget_k_values(cfg)}")

    report_label_mining(cons, cust, labels, cfg)
    report_pu_comparison(cons, cust, labels, cfg)
    report_threshold_sweep(cons, cust, labels, cfg)
    print("\nListo. Edita config/*.yaml con los valores elegidos y reejecuta 'lossan run --force'.")


if __name__ == "__main__":
    main()
