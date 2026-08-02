"""Tests end-to-end del pipeline sobre universo sintético (§19.5, §19.8)."""
import pandas as pd

from lossan.config import load_config
from lossan.lakehouse import Lakehouse, feeder_input_hash
from lossan.pipeline.runner import run
from lossan.synth import generate_universe


def test_generate_and_run_end_to_end(micro_config, tmp_path):
    root = str(tmp_path / "lake")
    counts = generate_universe(root, load_config())

    assert counts["feeders"] == 3
    assert counts["customers"] > 0
    assert counts["transformer_units"] >= counts["sites"]  # unidades > puestos

    result = run(root, workers=1)
    assert result["processed"] == 3
    assert result["skipped"] == 0

    lake = Lakehouse(root)
    balance = lake.read_entity("gold", "feeder_balance")
    status = lake.read_entity("gold", "feeder_status")

    assert len(balance) == 3
    assert len(status) == 3
    # Con hurto inyectado, la PNT debe ser positiva en el agregado.
    assert balance["pnt_kwh"].sum() > 0
    # Las pérdidas técnicas deben ser positivas.
    assert (balance["energy_technical_kwh"] > 0).all()

    # F2/F4/F6/F7/F8 integradas: entidades GOLD presentes y avance completo.
    assert not lake.read_entity("gold", "data_quality_findings").empty
    assert not lake.read_entity("gold", "powerflow_results").empty
    assert not lake.read_entity("gold", "zone_state_estimation").empty
    plan = lake.read_entity("gold", "inspection_plan")
    summary = lake.read_entity("gold", "campaign_summary")
    assert not plan.empty and not summary.empty
    # tras la priorización el avance llega al 100% (8/8 fases)
    assert (status["progress_pct"] == 100.0).all()


def test_incremental_reuse(micro_config, tmp_path):
    root = str(tmp_path / "lake")
    generate_universe(root, load_config())
    run(root, workers=1)
    # segunda corrida sin cambios -> todo reutilizado
    result2 = run(root, workers=1)
    assert result2["skipped"] == 3
    assert result2["processed"] == 0


def test_input_hash_stable():
    df = pd.DataFrame({"a": [3, 1, 2], "b": ["z", "x", "y"]})
    h1 = feeder_input_hash(df)
    h2 = feeder_input_hash(df.sample(frac=1.0, random_state=1))
    assert h1 == h2  # estable ante reordenamiento de filas


def test_pnt_tracks_injected_theft(micro_config, tmp_path):
    """La PNT estimada debe correlacionar con el hurto inyectado (§19.5)."""
    root = str(tmp_path / "lake")
    generate_universe(root, load_config())
    run(root, workers=1)

    lake = Lakehouse(root)
    balance = lake.read_entity("gold", "feeder_balance")
    labels = lake.read_entity("bronze", "theft_labels")

    injected = labels.groupby("feeder_id")["stolen_kwh"].sum()
    est = balance.set_index("feeder_id")["pnt_kwh"]
    # residuo del balance por alimentador debe ser pequeño
    assert (balance["residual_pct"].abs() < 0.5).all()
    # PNT estimada del mismo orden de magnitud que lo robado (± tolerancia amplia)
    for fid, inj in injected.items():
        if inj > 0:
            assert est[fid] > 0.5 * inj
