"""Fixtures: configuración a micro-escala para tests end-to-end rápidos."""
import shutil
from pathlib import Path

import pytest
import yaml

from lossan import config as cfgmod

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def micro_config(tmp_path, monkeypatch):
    """Copia config/ a un temporal y reduce la escala a un universo diminuto."""
    dst = tmp_path / "config"
    shutil.copytree(REPO / "config", dst)

    scale_file = dst / "scale.yaml"
    scale = yaml.safe_load(scale_file.read_text())
    scale["active_profile"] = "demo"
    scale["profiles"]["demo"] = {
        "feeders": 3,
        "customers_per_feeder_mean": 120,
        "poles_per_feeder_mean": 80,
        "history_months": 18,
        "theft_rate": 0.12,
        "seed": 42,
    }
    scale_file.write_text(yaml.safe_dump(scale))

    monkeypatch.setenv("LOSSAN_CONFIG_DIR", str(dst))
    cfgmod.reset_cache()
    yield dst
    cfgmod.reset_cache()
