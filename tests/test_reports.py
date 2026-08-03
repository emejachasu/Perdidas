"""Tests de reportes ejecutivos y ficha de inspección (§18)."""
import pytest

from lossan.config import load_config
from lossan.lakehouse import Lakehouse
from lossan.pipeline.runner import run
from lossan.reports import (consolidated_report, executive_report,
                            inspection_sheet)
from lossan.synth import generate_universe


@pytest.fixture()
def ran_lake(micro_config, tmp_path):
    cfg = load_config()
    cfg._scale["profiles"]["demo"].update(
        feeders=2, customers_per_feeder_mean=200, poles_per_feeder_mean=80,
        history_months=12)
    root = str(tmp_path / "lake")
    generate_universe(root, cfg)
    run(root, cfg=cfg, workers=1)
    return root, tmp_path


def test_executive_report_html(ran_lake):
    root, tmp = ran_lake
    out = executive_report(root, "F0000", str(tmp / "exec.pdf"), pdf=False)
    assert out.exists() and out.suffix == ".html"
    assert "Reporte ejecutivo" in out.read_text(encoding="utf-8")


def test_consolidated_report_html(ran_lake):
    root, tmp = ran_lake
    out = consolidated_report(root, str(tmp / "cons.pdf"), pdf=False)
    assert out.exists()
    assert "consolidado" in out.read_text(encoding="utf-8").lower()


def test_inspection_sheet_html(ran_lake):
    root, tmp = ran_lake
    plan = Lakehouse(root).read_entity("gold", "inspection_plan")
    if plan.empty:
        pytest.skip("sin plan de inspección")
    site = plan["site_id"].iloc[0]
    out = inspection_sheet(root, site, str(tmp / "ficha.pdf"), pdf=False)
    assert out.exists()
    assert "Ficha de inspección" in out.read_text(encoding="utf-8")
