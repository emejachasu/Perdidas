# lossan — Plataforma de Análisis de Pérdidas Técnicas y No Técnicas

Implementación en Python del [Requerimiento v3](docs/REQUERIMIENTO_v3.md) para
separar pérdidas técnicas de no técnicas (PNT) en redes de distribución, con
**dashboard web profesional que muestra el avance por alimentador**.

Este repositorio entrega la **fase F0 (fundacional, bloqueante)** más el dominio
crítico y el tablero, ejecutable end-to-end sobre un universo sintético.

---

## ¿Qué incluye esta entrega?

| Componente | Estado | Referencia |
|---|---|---|
| Estructura del paquete + `pyproject.toml` + CLI (`lossan`) | ✅ | §1.1, Anexo C |
| Configuración 100% externalizada (`config/*.yaml`) — nada de negocio en código | ✅ | §22.13 |
| Lakehouse Bronze/Silver/Gold sobre Parquet particionado + DuckDB | ✅ | §2.2 |
| Orquestación por alimentador + **incremental por `input_hash`** | ✅ | §2.3 |
| **Generador sintético a escala** (poste→puesto→unidad, bancos 1/2/3 uds. incl. delta abierto, hurtos inyectados) | ✅ | Anexo C |
| Modelo canónico `pydantic` + `lossan schema inspect` | ✅ | §4, §5 |
| **Jerarquía Poste→Puesto→Unidad con reglas de agregación §5.2** | ✅ | §5.2 |
| **Fórmulas P/Q/S/I y pérdidas §9.2** con tests de caso manual | ✅ | §9.2 |
| Balance jerárquico + PNT + cargabilidad por configuración de banco | ✅ | §13, §14.1 |
| Alumbrado público como término explícito del balance | ✅ | §10 |
| Esquema `field_inspections` (captura de campo) | ✅ | §23.1 |
| **Dashboard web por alimentador** (Streamlit + Plotly, con pestañas) | ✅ | §18 |
| **Topología `rustworkx` + trazas + zonas de protección + transferencias** | ✅ F2 | §6, §7 |
| **Reglas de calidad de datos R01–R25** (motor por YAML) | ✅ F2 | §8 |
| **Flujo de potencia propio (BFS) + exportador OpenDSS + validación cruzada** | ✅ F4 | §11 |
| **Minería de etiquetas M1–M8 + PU learning (Elkan–Noto/Bagging/spies) + SHAP + Precision@k** | ✅ F7 | §15 |
| **Estimación de estado WLS + ramales sin medición (reconciliación por zona)** | ✅ F6 | §14.3 |
| **Priorización 4 M USD (mochila MILP OR-Tools) + reserva de exploración + clustering + ruteo** | ✅ F8 | §17 |
| Suite de pruebas (fórmulas, bancos, topología, flujo, estado, ML, campaña, e2e) | ✅ | §19 |

El pipeline completa **8/8 fases (100 %)** sobre el universo sintético. El
dashboard refleja el avance real por alimentador.

---

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dashboard,dev]"
```

## Uso rápido

```bash
# 1) Generar el universo sintético (perfil 'demo' = 12 alimentadores)
lossan generate

# 2) Ejecutar el pipeline por alimentador (incremental por hash)
lossan run

# 3) Ver el avance en consola
lossan status

# Tamizaje masivo rápido (sin fases pesadas) y prueba de escala:
lossan run --level n1
lossan bench --feeders 24 --target 960

# 4) Abrir el dashboard web por alimentador
lossan dashboard        # http://localhost:8501
```

Cambia la escala en `config/scale.yaml` (`active_profile: demo | full`), o
`lossan generate --profile full` para el universo objetivo (960 alimentadores).

### Entrada/salida GIS (File Geodatabase)

```bash
lossan schema template --out mi_modelo.yaml # PLANTILLA para modelar tu SIG (campos+tipos)
lossan fgdb-layers  ruta/a/red.gdb          # inspeccionar capas de una FGDB
lossan ingest-fgdb  ruta/a/red.gdb          # ingerir red a BRONZE (mapeo en config/schema_mapping.yaml)
lossan ingest-consumption consumo.csv       # consumo histórico del sistema comercial
lossan ingest-header cabecera.csv           # medidor de cabecera por alimentador/mes
lossan feeder-report F0000                  # elementos conectados por traza + desglose de pérdidas
lossan export-sample --fmt fgdb             # datos de prueba (CSV + GPKG + FileGDB)
lossan export-results --fmt fgdb            # capas de resultados para ArcGIS (§18)
lossan report --feeder F0000                # reporte ejecutivo PDF (o --consolidado)
lossan inspection-sheet F0000-TS0007        # ficha de inspección por puesto/poste
```

**Orquestación con Dagster** (§2.3): `dagster dev -m lossan.orchestration.dagster_defs`
(assets particionados por alimentador, incremental por hash).

Lectura/escritura de FGDB con GDAL/OpenFileGDB (**sin `arcpy`**, §2.5).

**Documentación:**
**[Arquitectura](docs/ARQUITECTURA.md)** ·
**[Referencia de módulos y funciones](docs/REFERENCIA.md)** ·
**[Análisis de brechas](docs/BRECHAS.md)** ·
**[Revisión de correctitud](docs/REVISION.md)**

**Guías:**
**[Datos requeridos (inventario)](docs/DATOS_REQUERIDOS.md)** ·
**[Modelo de datos y conectividad](docs/DATA_MODEL.md)** ·
**[Histórico necesario](docs/HISTORIA.md)** ·
**[Windows paso a paso](docs/WINDOWS.md)** · **[Calibración](docs/TUNING.md)**

**Ejemplo de calibración:** `python examples/calibrate.py --root data/lake --feeder F0000`
o el notebook con gráficos `examples/calibrate.ipynb`
(mide Precision@k contra la verdad-terreno, compara métodos PU y barre umbrales).

**Plantillas de datos vacías** (CSV + Excel con diccionario) para que los
equipos las llenen: `lossan data-templates --out export/plantillas`.

## Pruebas

```bash
pytest -q
```

---

## Arquitectura

```
config/                 # TODOS los parámetros (escala, presupuesto, eléctricos, umbrales)
src/lossan/
  config.py             # cargador de configuración cacheado
  cli.py                # CLI Typer
  domain/               # modelo canónico
    enums.py
    models.py           # entidades pydantic
    bank.py             # §5.2 capacidad y pérdidas por configuración de banco
  electrical/
    formulas.py         # §9.2 P, Q, S, I, pérdidas, corriente de neutro
  lakehouse/
    storage.py          # Bronze/Silver/Gold + DuckDB + hash incremental
  synth/
    generator.py        # generador de datos sintéticos parametrizable
  topology/             # F2
    graph.py            # grafo rustworkx + trazas (downstream/upstream/path/subtree)
    zones.py            # zonas de protección (ramal operativo)
    dynamic.py          # versiones topológicas + inferencia de transferencias
    quality.py          # motor de reglas R01-R25
  powerflow/            # F4
    sweep.py            # motor propio backward-forward sweep
    opendss_export.py   # exportador .dss (Line, Load, Transformer por unidad)
    validate.py         # comparación automática de motores + caso canónico
  ml/                   # F7
    label_mining.py     # mecanismos M1-M8
    features.py         # features anti-fuga con corte temporal
    pu.py               # Elkan-Noto, Bagging PU, two-step spies
    risk.py             # ensamble + isotónica + SHAP + Precision@k
  stateest/             # F6
    estimate.py         # WLS + residuos normalizados + reconciliación por zona
  prioritization/       # F8
    economics.py        # beneficio/costo/ROI por PUESTO (no por cliente)
    optimize.py         # mochila MILP OR-Tools + greedy + dos etapas + exploración
    routing.py          # HDBSCAN + secuenciación + órdenes de trabajo
    plan.py             # plan de campaña + rankings entregables
  pipeline/
    technical.py        # física de pérdidas técnicas (compartida)
    balance.py          # balance jerárquico, PNT, cargabilidad
    analyze.py          # orquestación F2+F3/F5+F4+F6+F7 por alimentador
    prioritization_step.py  # F8 a nivel de sistema + marca de avance
    runner.py           # orquestación por alimentador + avance + transferencias
  dashboard/
    app.py              # dashboard web por alimentador (pestañas)
tests/                  # fórmulas, bancos, topología, flujo, ML, end-to-end
```

### Decisiones de diseño clave

- **El alimentador es la unidad de partición y paralelización** (§2.3): cada uno
  cabe en memoria; el `input_hash` evita recomputar lo que no cambió.
- **Capacidad y pérdidas SIEMPRE por unidad, agregadas al puesto** (§5.2): el
  delta abierto rinde `√3·S` (86,6 % de `2S`), no `2S`; los bancos desiguales se
  evalúan como `3·min`, no como la suma; `P0`/`Pk` se suman por unidad.
- **Ningún valor de negocio en el código** (§22.13): toda volumetría, costo,
  tarifa y umbral vive en `config/`.
- **Núcleo independiente de `arcpy`** (§2.5): el dominio no importa ArcGIS.

---

## Nota de alcance

El requerimiento v3 describe una plataforma de 23 módulos y 10 fases. Esta
entrega prioriza lo que el propio documento marca como **bloqueante (F0)** y de
**mayor valor inmediato (F3, cálculo correcto de P/Q/S)**, junto con el
**dashboard por alimentador** solicitado. Las fases F2/F4/F6/F7/F8 quedan
diseñadas como interfaces y roadmap explícito, listas para implementarse sobre
esta base sin reescritura.
