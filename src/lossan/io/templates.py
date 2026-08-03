"""Generador de plantillas vacías (CSV + Excel) por cada dato requerido.

Para que los equipos de SIG, Comercial y Operación llenen los datos con las
columnas exactas que el sistema espera. La especificación refleja el diccionario
de datos canónico (docs/DATA_MODEL.md) y el inventario (docs/DATOS_REQUERIDOS.md).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# entidad -> (origen, [(columna, requerido, descripción, ejemplo)])
TEMPLATES: dict[str, tuple[str, list[tuple]]] = {
    "poles": ("SIG", [
        ("pole_id", True, "Id único del poste", "F0001-P00001"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("x", True, "Coordenada X (o desde geometría)", "512340.5"),
        ("y", True, "Coordenada Y (o desde geometría)", "9876540.2"),
        ("pole_type", False, "Tipo/material", "concrete"),
        ("height_m", False, "Altura (m)", "11"),
    ]),
    "sites": ("SIG", [
        ("site_id", True, "Id del puesto", "F0001-TS0007"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("pole_id", False, "Poste que lo aloja", "F0001-P00001"),
        ("kind", True, "transformer|customer|switching|metering|streetlight", "transformer"),
        ("bank_config", False, "single|wye_closed|delta_closed|open_delta|delta_4wire", "open_delta"),
        ("node_id", False, "Nodo eléctrico del puesto", "F0001-N0007"),
    ]),
    "transformer_units": ("SIG", [
        ("unit_id", True, "Id de la unidad", "F0001-TS0007-U0"),
        ("site_id", True, "Puesto al que pertenece", "F0001-TS0007"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("sn_kva", True, "Potencia nominal (kVA)", "50"),
        ("p0_kw", False, "Pérdidas de vacío (kW)", "0.125"),
        ("pk_kw", False, "Pérdidas de carga nominal (kW)", "0.55"),
        ("voltage_ln", False, "Tensión nominal LN (V)", "220"),
        ("phase", False, "Fase(s): A|B|C|AB|BC|CA|ABC", "AB"),
    ]),
    "segments": ("SIG", [
        ("segment_id", True, "Id del tramo", "F0001-S00012"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("node_from", True, "Nodo aguas arriba", "F0001-N0003"),
        ("node_to", True, "Nodo aguas abajo", "F0001-N0007"),
        ("conductor_code", True, "Código de conductor (catálogo)", "ACSR_2/0"),
        ("phase", True, "Fases del tramo", "ABC"),
        ("voltage_ll", True, "Tensión LL (V)", "13800"),
        ("r_ohm_per_km", False, "R (Ω/km) si no viene del catálogo", "0.441"),
        ("x_ohm_per_km", False, "X (Ω/km)", "0.39"),
        ("ampacity_a", False, "Ampacidad (A)", "270"),
        ("length_m", False, "Longitud (m) o desde geometría", "85.2"),
        ("section", False, "primary|secondary", "primary"),
        ("material", False, "al|cu", "al"),
    ]),
    "customers": ("Comercial/SIG", [
        ("customer_unit_id", True, "Id de la unidad de servicio (medidor)", "F0001-C000123"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("site_id", True, "Puesto de cliente (acometida compartida)", "F0001-CS000123"),
        ("transformer_site_id", False, "Puesto de transformación (mejor por traza)", "F0001-TS0007"),
        ("pole_id", False, "Poste de la acometida", "F0001-P00001"),
        ("tariff_class", True, "residential|commercial|industrial|streetlight_led", "residential"),
        ("installed_load_kw", False, "Carga instalada (kW)", "3.5"),
        ("service_drop_kva", False, "Capacidad de acometida (kVA)", "5"),
    ]),
    "streetlights": ("SIG", [
        ("streetlight_id", True, "Id de la luminaria", "F0001-L00001"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("transformer_site_id", False, "Puesto de transformación", "F0001-TS0007"),
        ("technology", True, "led|sodium|mercury|metal_halide", "led"),
        ("lamp_w", True, "Potencia de lámpara (W)", "100"),
    ]),
    "switching_devices": ("SIG/SCADA", [
        ("device_id", True, "Id del dispositivo", "F0001-DV001"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("node_id", True, "Nodo donde está", "F0001-N0007"),
        ("type", True, "seccionador|reconectador|interruptor|fusible|seccionador_enlace", "reconectador"),
        ("normal_state", True, "NA (abierto) | NC (cerrado)", "NC"),
    ]),
    "consumption": ("Comercial", [
        ("customer_unit_id", True, "Id de la unidad de servicio", "F0001-C000123"),
        ("feeder_id", True, "Alimentador", "F0001"),
        ("year_month", True, "Periodo YYYY-MM", "2024-01"),
        ("kwh", True, "Energía activa facturada (kWh)", "180.5"),
        ("kvarh", False, "Energía reactiva (kVArh) — recomendado", "62.0"),
        ("estimated", False, "Lectura estimada (true/false)", "false"),
    ]),
    "header_meters": ("Comercial/SCADA", [
        ("feeder_id", True, "Alimentador", "F0001"),
        ("year_month", True, "Periodo YYYY-MM", "2024-01"),
        ("kwh", True, "Energía de cabecera (kWh)", "2450000"),
        ("kvarh", False, "Energía reactiva de cabecera", "857500"),
    ]),
    "switching_events": ("SCADA/DMS", [
        ("device_id", True, "Dispositivo", "F0001-DV001"),
        ("timestamp", True, "Fecha/hora del evento", "2024-03-15 14:32:00"),
        ("estado_previo", True, "NA|NC", "NC"),
        ("estado_nuevo", True, "NA|NC", "NA"),
        ("motivo", False, "maniobra|falla|transferencia", "transferencia"),
        ("operador", False, "Operador", "J.Perez"),
    ]),
    "field_inspections": ("Campo", [
        ("inspection_id", True, "Id de la inspección", "INS-0001"),
        ("site_id", True, "Puesto inspeccionado", "F0001-TS0007"),
        ("customer_unit_id", False, "Unidad de cliente (si aplica)", "F0001-C000123"),
        ("inspected_date", True, "Fecha (YYYY-MM-DD)", "2024-05-10"),
        ("finding", True, "Hallazgo de hurto (true/false)", "true"),
        ("finding_type", False, "Tipo de hallazgo", "derivacion_directa"),
        ("recovered_kwh", False, "Energía recuperada (kWh)", "3200"),
        ("actual_cost_usd", False, "Costo real de la visita (USD)", "42"),
        ("source", False, "directed|exploration", "directed"),
    ]),
}


def build_templates(out_dir: str) -> dict:
    """Escribe una carpeta con un CSV vacío por dato + un Excel multi-hoja."""
    out = Path(out_dir)
    csv_dir = out / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for entity, (_src, cols) in TEMPLATES.items():
        headers = [c[0] for c in cols]
        pd.DataFrame(columns=headers).to_csv(csv_dir / f"{entity}.csv", index=False)
        written.append(entity)

    xlsx = out / "plantillas_datos.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        # hoja índice / diccionario
        dic_rows = []
        for entity, (src, cols) in TEMPLATES.items():
            for (col, req, desc, ex) in cols:
                dic_rows.append({"entidad": entity, "origen": src, "columna": col,
                                 "requerido": "SÍ" if req else "opcional",
                                 "descripción": desc, "ejemplo": ex})
        pd.DataFrame(dic_rows).to_excel(xw, sheet_name="Diccionario", index=False)
        # una hoja por entidad con encabezados + fila de ejemplo
        for entity, (_src, cols) in TEMPLATES.items():
            headers = [c[0] for c in cols]
            example = {c[0]: c[3] for c in cols}
            df = pd.DataFrame([example], columns=headers)
            df.to_excel(xw, sheet_name=entity[:31], index=False)

    return {"csv": [str(csv_dir / f"{e}.csv") for e in written],
            "xlsx": str(xlsx), "entities": written}
