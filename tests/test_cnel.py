"""Tests del adaptador del modelo de datos de CNEL EP (SIGELEC/ArcFM).

Cubre la jerarquía real: Estructura → Puesto → Unidad y, sobre todo, el caso
del **edificio**: 1 PuntoCarga con N CONEXIONCONSUMIDOR.
"""
import pandas as pd
import pytest

from lossan.config import load_config
from lossan.io.cnel import (build_canonical, decode_bank_config, decode_phase,
                            load_cnel_mapping, parse_kva, site_unit_summary)
from lossan.pipeline.loadpoint import aggregate_load_points, load_point_findings


# --------------------------------------------------------------- dominios

def test_decode_phase_bitmask():
    dom = load_cnel_mapping()["domains"]["phase_designation"]
    assert decode_phase(4, dom) == "A"
    assert decode_phase(2, dom) == "B"
    assert decode_phase(1, dom) == "C"
    assert decode_phase(7, dom) == "ABC"
    assert decode_phase(6, dom) == "AB"
    assert decode_phase("ABC", dom) == "ABC"      # ya viene como letras
    assert decode_phase(None, dom) is None


def test_decode_bank_config_from_domain_and_fallback():
    dom = load_cnel_mapping()["domains"]["bank_config"]
    assert decode_bank_config("Delta Abierta", dom) == "open_delta"
    assert decode_bank_config("MONOFASICO", dom) == "single"
    assert decode_bank_config("Estrella Cerrada", dom) == "wye_closed"
    # valor desconocido: NO inventa, deduce por nº de unidades y lo acota
    assert decode_bank_config("???", dom, n_units=2) == "open_delta"
    assert decode_bank_config(None, dom, n_units=3) == "wye_closed"
    assert decode_bank_config(None, dom, n_units=1) == "single"


def test_parse_kva_from_domain_text():
    assert parse_kva("50 kVA") == 50.0
    assert parse_kva("37,5") == 37.5
    assert parse_kva(100) == 100.0
    assert parse_kva(None) is None


# ------------------------------------------------- jerarquía puesto/unidad

def _cnel_layers():
    """Capas CNEL mínimas con un EDIFICIO (1 punto de carga, 3 medidores)."""
    estructuras = pd.DataFrame({
        "GLOBALID": ["{E1}", "{E2}"], "ALIMENTADORID": ["ALIM01"] * 2,
        "TIPOESTRUCTURA": ["POSTE HC", "POSTE HC"], "ALTURA": [11.0, 11.0],
    })
    puestos = pd.DataFrame({
        "GLOBALID": ["{TS1}", "{TS2}"], "ALIMENTADORID": ["ALIM01"] * 2,
        "CODIGOPUESTO": ["PT-001", "PT-002"],
        "ESTRUCTURASOPORTEGLOBALID": ["{E1}", "{E2}"],
        "CONFIGURACIONLADOBAJA": ["Delta Abierta", "Monofasico"],
        "FASECONEXION": [6, 4], "VOLTAJE": [13800, 13800],
        "POTENCIAKVA": [75.0, 50.0], "MEDIDO": [0, 0],
        "CIRCUITSOURCEGUID": ["{CS1}", "{CS2}"],
    })
    unidades = pd.DataFrame({           # TS1 = banco de 2 (delta abierto), TS2 = 1
        "GLOBALID": ["{U1}", "{U2}", "{U3}"],
        "PUESTOTRANSFDISTGLOBALID": ["{TS1}", "{TS1}", "{TS2}"],
        "ALIMENTADORID": ["ALIM01"] * 3,
        "POTENCIANOMINAL": ["37.5 kVA", "37.5 kVA", "50 kVA"],
        "TENSIONLADOALTA": [13800] * 3, "FASECONEXION": [4, 2, 4],
        "NUMEROSERIE": ["S1", "S2", "S3"], "MARCA": ["X"] * 3, "MODELO": ["M"] * 3,
        "TIPO": [1, 1, 1],
    })
    # PC1 es el EDIFICIO: 3 conexiones consumidor; PC2 es una casa: 1 conexión
    puntos = pd.DataFrame({
        "GLOBALID": ["{PC1}", "{PC2}"], "ALIMENTADORID": ["ALIM01"] * 2,
        "PUESTOTRANSFDISTGLOBALID": ["{TS1}", "{TS2}"],
        "ESTRUCTURASOPORTEGLOBALID": ["{E1}", "{E2}"],
        "FASECONEXION": [7, 4], "RUTALECTURA": ["R1", "R2"],
        "SECUENCIALECTURA": ["1", "2"],
        "COORD_X": [100.0, 200.0], "COORD_Y": [100.0, 200.0],
    })
    conexiones = pd.DataFrame({
        "GLOBALID": ["{C1}", "{C2}", "{C3}", "{C4}"],
        "PUNTOCARGAGLOBALID": ["{PC1}", "{PC1}", "{PC1}", "{PC2}"],
        "ALIMENTADORID": ["ALIM01"] * 4,
        "CODIGOUNICO": ["CU-001", "CU-002", "CU-003", "CU-004"],
        "CODIGOCLIENTE": ["CLI-1", "CLI-2", "CLI-3", "CLI-4"],
        "MDENUMFAB": ["M1", "M2", "M3", "M4"], "MEDMAR": ["A"] * 4,
        "TIPOMEDIDOR": ["MONO"] * 4, "SECUENCIAFASE": [4, 2, 1, 4],
        "PREPAGO": ["NO"] * 4, "ESTADO": [1] * 4,
    })
    return {
        "EstructuraSoporte": estructuras,
        "PuestoTransfDistribucion": puestos,
        "UNIDADTRANSFDISTRIBUCION": unidades,
        "PuntoCarga": puntos,
        "CONEXIONCONSUMIDOR": conexiones,
    }


def test_building_one_load_point_many_connections():
    """El caso declarado: en un edificio hay 1 punto de carga y N conexiones."""
    canon = build_canonical(_cnel_layers(), load_cnel_mapping())
    lps, cust = canon["load_points"], canon["customers"]
    assert len(lps) == 2 and len(cust) == 4
    per_lp = cust.groupby("site_id").size()
    assert per_lp["{PC1}"] == 3       # el edificio
    assert per_lp["{PC2}"] == 1
    # cada conexión hereda el transformador y el poste de SU punto de carga
    edificio = cust[cust["site_id"] == "{PC1}"]
    assert set(edificio["transformer_site_id"]) == {"{TS1}"}
    assert set(edificio["pole_id"]) == {"{E1}"}
    # el código comercial viaja para cruzar con el consumo
    assert set(edificio["customer_code"]) == {"CLI-1", "CLI-2", "CLI-3"}


def test_bank_from_cnel_configuration_field():
    """La configuración de banco viene del SIG; no hay que inferirla (§5.2)."""
    canon = build_canonical(_cnel_layers(), load_cnel_mapping())
    sites = canon["sites"].set_index("site_id")
    assert sites.loc["{TS1}", "bank_config"] == "open_delta"
    assert sites.loc["{TS2}", "bank_config"] == "single"
    units = canon["transformer_units"]
    assert units.groupby("site_id").size()["{TS1}"] == 2
    # kVA parseado del texto de dominio y fase por unidad decodificada
    assert set(units.loc[units["site_id"] == "{TS1}", "sn_kva"]) == {37.5}
    assert set(units.loc[units["site_id"] == "{TS1}", "phase"]) == {"A", "B"}


def test_open_delta_capacity_uses_cnel_config():
    """El puesto TS1 (delta abierto, 2x37,5) debe rendir √3·37,5, no 75."""
    import math

    from lossan.domain.bank import UnitPlate, bank_capacity
    from lossan.domain.enums import BankConfig
    canon = build_canonical(_cnel_layers(), load_cnel_mapping())
    units = canon["transformer_units"]
    g = units[units["site_id"] == "{TS1}"]
    plates = [UnitPlate(float(r.sn_kva), 0.1, 0.5, 220.0) for r in g.itertuples()]
    cfg_bank = BankConfig(canon["sites"].set_index("site_id").loc["{TS1}", "bank_config"])
    cap, _ = bank_capacity(cfg_bank, plates)
    assert cap == pytest.approx(math.sqrt(3) * 37.5)
    assert cap < 75.0     # NO es la suma aritmética


def test_hierarchy_summary_reports_multiunit():
    canon = build_canonical(_cnel_layers(), load_cnel_mapping())
    summary = site_unit_summary(canon).set_index("relacion")
    tx = summary.loc["PuestoTransfDistribucion -> UNIDADTRANSFDISTRIBUCION"]
    assert tx["hijos_por_padre_max"] == 2 and tx["padres_multi"] == 1
    lp = summary.loc["PuntoCarga -> CONEXIONCONSUMIDOR"]
    assert lp["hijos_por_padre_max"] == 3 and lp["padres_multi"] == 1


# ------------------------------------------ modelo eléctrico por punto de carga

def test_coincidence_applied_at_load_point_not_per_meter():
    """La coincidencia se aplica sobre el punto de carga (§5.3.2)."""
    canon = build_canonical(_cnel_layers(), load_cnel_mapping())
    cust = canon["customers"].copy()
    cust["tariff_class"] = "residential"
    cust["service_drop_kva"] = 10.0
    cons = pd.DataFrame([
        {"customer_unit_id": c, "feeder_id": "ALIM01", "year_month": ym, "kwh": 200.0}
        for c in cust["customer_unit_id"] for ym in ("2024-01", "2024-02")
    ])
    lp = aggregate_load_points(cons, cust, load_config())
    edificio = lp.set_index("load_point_id").loc["{PC1}"]
    assert edificio["n_connections"] == 3
    # la demanda diversificada del punto es MENOR que la suma de los picos
    assert edificio["p_max_diversified_kw"] < edificio["sum_of_peaks_kw"]


def test_intra_load_point_dispersion_finding():
    """Una conexión muy por debajo de sus pares del mismo punto = hallazgo."""
    canon = build_canonical(_cnel_layers(), load_cnel_mapping())
    cust = canon["customers"].copy()
    cust["tariff_class"] = "residential"
    cust["service_drop_kva"] = 10.0
    kwh = {"CU-001": 300.0, "CU-002": 300.0, "CU-003": 20.0,
           "CU-004": 250.0}   # CU-003 muy por debajo de sus pares del punto
    cons = pd.DataFrame([
        {"customer_unit_id": c, "feeder_id": "ALIM01", "year_month": ym, "kwh": kwh[c]}
        for c in kwh for ym in ("2024-01", "2024-02")
    ])
    lp = aggregate_load_points(cons, cust, load_config())
    findings = load_point_findings(lp, load_config())
    assert "dispersion_intra_punto" in set(findings["finding"])
    assert "{PC1}" in set(findings.loc[findings["finding"] == "dispersion_intra_punto",
                                       "load_point_id"])


# ------------------------------- identificadores únicos y cruce comercial

def _cnel_layers_with_attributes():
    """Capas CNEL + ATRIBUTOSCONSUMIDOR (CUENTACONTRATO, tarifa, carga)."""
    layers = _cnel_layers()
    layers["ATRIBUTOSCONSUMIDOR"] = pd.DataFrame({
        "CODIGOUNICO": ["CU-001", "CU-002", "CU-003", "CU-004"],
        "CUENTACONTRATO": ["CC-100", "CC-101", "CC-102", "CC-103"],
        "TIPOTARIFA": ["RESIDENCIAL", "COMERCIAL", "RESIDENCIAL-A", "INDUSTRIAL"],
        "CATEGORIA": ["A", "B", "A", "C"],
        "POTENCIAACTIVA": [3.5, 12.0, 4.0, 45.0],
        "POTENCIAREACTIVA": [1.0, 4.0, 1.2, 15.0],
        "CDAFAS": [1, 1, 1, 3],
        "EDCCOD": ["A", "A", "A", "A"],
        "NUMMEDIDOR": ["M1", "M2", "M3", "M4"],
        "CONSUMOPROMEDIO": [200.0, 800.0, 150.0, 4000.0],
    })
    return layers


def test_codigounico_is_the_unique_identifier():
    """El id canónico de la conexión es CODIGOUNICO, no el GLOBALID."""
    canon = build_canonical(_cnel_layers_with_attributes(), load_cnel_mapping())
    cust = canon["customers"]
    assert set(cust["customer_unit_id"]) == {"CU-001", "CU-002", "CU-003", "CU-004"}
    assert "global_id" in cust.columns          # el GLOBALID se conserva
    assert cust["customer_unit_id"].is_unique


def test_cuentacontrato_and_tariff_from_attributes():
    """ATRIBUTOSCONSUMIDOR aporta CUENTACONTRATO y la clase tarifaria."""
    canon = build_canonical(_cnel_layers_with_attributes(), load_cnel_mapping())
    cust = canon["customers"].set_index("customer_unit_id")
    assert cust.loc["CU-001", "cuenta_contrato"] == "CC-100"
    assert cust.loc["CU-001", "tariff_class"] == "residential"
    assert cust.loc["CU-002", "tariff_class"] == "commercial"
    assert cust.loc["CU-003", "tariff_class"] == "residential"   # variante '-A'
    assert cust.loc["CU-004", "tariff_class"] == "industrial"
    assert cust.loc["CU-004", "installed_load_kw"] == 45.0


def test_consumption_linked_by_cuenta_contrato():
    """El consumo comercial entra por CUENTACONTRATO y se traduce a CODIGOUNICO."""
    from lossan.io import link_consumption_to_connections
    canon = build_canonical(_cnel_layers_with_attributes(), load_cnel_mapping())
    cust = canon["customers"]
    cons = pd.DataFrame({
        "cuenta_contrato": ["CC-100", "CC-101", "CC-999"],   # la última no existe
        "year_month": ["2024-01"] * 3, "kwh": [100.0, 200.0, 50.0],
    })
    linked, stats = link_consumption_to_connections(cons, cust)
    assert linked.loc[0, "customer_unit_id"] == "CU-001"
    assert linked.loc[1, "customer_unit_id"] == "CU-002"
    assert pd.isna(linked.loc[2, "customer_unit_id"])   # sin conexión en el SIG
    assert stats["matched"] == 2 and stats["unmatched"] == 1


# ------------------------------------------- zonas por trazado nativo ArcFM

def test_zones_from_arcfm_trace():
    """ArcFM ya resuelve la traza: la zona se obtiene agrupando por el GUID."""
    from lossan.topology import build_zones_from_arcfm
    devices = pd.DataFrame({"device_id": ["{D1}", "{D2}"],
                            "node_id": ["{CSD1}", "{CSD2}"]})
    sites = pd.DataFrame({"site_id": ["{TS1}", "{TS2}", "{TS3}"],
                          "parent_circuit_source": ["{CSD1}", "{CSD1}", "{CSD2}"]})
    customers = pd.DataFrame({"customer_unit_id": ["a", "b", "c"],
                              "parent_circuit_source": ["{CSD1}", "{CSD2}", "{CSD2}"]})
    z = build_zones_from_arcfm(devices, {"sites": sites, "customers": customers},
                               "ALIM01").set_index("zone_id")
    assert z.loc["{CSD1}", "n_tx_sites"] == 2
    assert z.loc["{CSD1}", "n_customers"] == 1
    assert z.loc["{CSD2}", "n_tx_sites"] == 1
    assert z.loc["{CSD2}", "n_customers"] == 2
    assert set(z["source"]) == {"arcfm_trace"}


def test_missing_codigounico_falls_back_to_globalid():
    """Sin CODIGOUNICO la conexión NO puede desaparecer del balance."""
    layers = _cnel_layers()
    cc = layers["CONEXIONCONSUMIDOR"].copy()
    cc.loc[0, "CODIGOUNICO"] = None      # dato faltante en producción
    cc.loc[1, "CODIGOUNICO"] = "   "     # vacío
    layers["CONEXIONCONSUMIDOR"] = cc
    canon = build_canonical(layers, load_cnel_mapping())
    cust = canon["customers"]
    assert len(cust) == 4                       # ninguna se pierde
    assert cust["customer_unit_id"].notna().all()
    assert cust.loc[0, "customer_unit_id"] == "{C1}"   # cayó al GLOBALID
    assert cust.loc[2, "customer_unit_id"] == "CU-003"  # el resto conserva el suyo
