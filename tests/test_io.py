"""Tests de los adaptadores de I/O (FGDB, muestra, consumo)."""
import pandas as pd

from lossan.config import load_config
from lossan.io import ingest_consumption, ingest_header
from lossan.lakehouse import Lakehouse
from lossan.synth import generate_universe


def test_ingest_consumption_from_csv(micro_config, tmp_path):
    csv = tmp_path / "cons.csv"
    pd.DataFrame({
        "customer_unit_id": ["C1", "C1", "C2"],
        "feeder_id": ["F0", "F0", "F0"],
        "year_month": ["2022-01", "2022-02", "2022-01"],
        "kwh": [100, 110, 50],
        "kvarh": [30, 33, 15],
    }).to_csv(csv, index=False)
    root = str(tmp_path / "lake")
    res = ingest_consumption(str(csv), root)
    assert res["customers"] == 2 and res["months"] == 2
    df = Lakehouse(root).read_entity("bronze", "consumption", "F0")
    assert len(df) == 3 and set(df["customer_unit_id"]) == {"C1", "C2"}


def test_ingest_consumption_with_field_map(micro_config, tmp_path):
    csv = tmp_path / "cons.csv"
    pd.DataFrame({
        "CTA": ["C1"], "ALIM": ["F9"], "PERIODO": ["2022-05-01"], "CONSUMO": [200],
    }).to_csv(csv, index=False)
    root = str(tmp_path / "lake")
    fmap = {"customer_unit_id": "CTA", "feeder_id": "ALIM",
            "year_month": "PERIODO", "kwh": "CONSUMO"}
    res = ingest_consumption(str(csv), root, field_map=fmap)
    assert res["records"] == 1
    df = Lakehouse(root).read_entity("bronze", "consumption", "F9")
    assert df["year_month"].iloc[0] == "2022-05"   # normalizado a YYYY-MM


def test_export_sample_roundtrip_gpkg(micro_config, tmp_path):
    lake_root = str(tmp_path / "lake")
    generate_universe(lake_root, load_config())
    from lossan.io import export_sample
    out = tmp_path / "export"
    res = export_sample(lake_root, str(out), fmt="gpkg", feeders=["F0000"])
    assert "poles" in res["gis_layers"]
    assert (out / "csv" / "consumption.csv").exists()


def test_build_templates(tmp_path):
    from lossan.io import build_templates, TEMPLATES
    res = build_templates(str(tmp_path / "plantillas"))
    assert set(res["entities"]) == set(TEMPLATES.keys())
    # CSV con encabezados canónicos, sin filas
    import pandas as pd
    df = pd.read_csv(tmp_path / "plantillas" / "csv" / "consumption.csv")
    assert list(df.columns) == ["customer_unit_id", "feeder_id", "year_month",
                                "kwh", "kvarh", "estimated"]
    assert len(df) == 0
    assert (tmp_path / "plantillas" / "plantillas_datos.xlsx").exists()
