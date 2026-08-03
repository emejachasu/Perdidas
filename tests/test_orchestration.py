"""Test de la integración Dagster (§2.3). Se omite si dagster no está instalado."""
import pytest

pytest.importorskip("dagster")


def test_dagster_defs_load():
    from lossan.orchestration.dagster_defs import defs, feeder_parts
    assert defs is not None
    # dos assets: por alimentador y de sistema
    assets = list(defs.get_all_asset_specs()) if hasattr(defs, "get_all_asset_specs") else None
    # las particiones existen (al menos una)
    assert len(feeder_parts.get_partition_keys()) >= 1
