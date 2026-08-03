# Arquitectura de la plataforma

Plataforma analítica en Python para separar pérdidas técnicas y no técnicas
(PNT) en redes de distribución. Diseño **por capas**, **particionado por
alimentador** y **desacoplado de `arcpy`** (§2.5).

## 1. Visión por capas

```mermaid
flowchart TB
    subgraph FUENTES["Fuentes de datos"]
        FGDB[(File Geodatabase<br/>ArcGIS/ArcFM)]
        COM[(Sistema Comercial<br/>consumo, cabecera)]
        SCADA[(SCADA/DMS<br/>log de conmutación)]
        CAMPO[(Campo<br/>inspecciones)]
    end
    subgraph INGESTA["Adaptadores I/O  (lossan.io)"]
        A1[ingest_fgdb<br/>GDAL/OpenFileGDB]
        A2[ingest_consumption<br/>ingest_header]
    end
    subgraph LAKE["Lakehouse  (DuckDB + Parquet)"]
        BR[[BRONZE<br/>crudo inmutable]]
        SI[[SILVER<br/>canónico validado]]
        GO[[GOLD<br/>resultados]]
    end
    subgraph NUCLEO["Núcleo analítico  (por alimentador)"]
        T[topology<br/>F2]
        E[electrical<br/>F3]
        P[powerflow<br/>F4]
        B[pipeline.balance<br/>F5]
        S[stateest<br/>F6]
        M[ml<br/>F7]
        PR[prioritization<br/>F8]
    end
    subgraph SALIDA["Salidas"]
        DASH[Dashboard<br/>Streamlit]
        GIS[Capas GIS<br/>GPKG/FGDB]
        REP[Reportes/CSV]
    end
    FGDB --> A1 --> BR
    COM --> A2 --> BR
    SCADA --> BR
    CAMPO --> BR
    BR --> SI --> NUCLEO --> GO
    GO --> DASH
    GO --> GIS
    GO --> REP
    CONF[/config/*.yaml<br/>escala, presupuesto, umbrales/] -.-> NUCLEO
```

- **BRONZE** — extracto crudo, inmutable, con hash de origen. Parquet.
- **SILVER** — modelo canónico normalizado y validado (`pydantic`). Parquet
  particionado por `feeder_id` (consumo también por `year_month`).
- **GOLD** — resultados: balance, pérdidas, riesgo, plan. Publicación selectiva.
- **DuckDB** como motor analítico sobre Parquet (una máquina, sin servidor).
- **Toda la parametrización** (volumetría, costos, tarifas, umbrales) vive en
  `config/` — nada en el código (§22.13).

## 2. El alimentador como unidad atómica

```mermaid
flowchart LR
    subgraph RUN["lossan run"]
      direction TB
      L[list_feeders] --> H{¿input_hash<br/>cambió?}
      H -- no --> SK[reutiliza GOLD]
      H -- sí --> AF[analyze_feeder_full]
      AF --> W[escribe GOLD<br/>+ marca avance]
    end
    SYS1[detección de transferencias<br/>§7.4] -.nivel sistema.-> RUN
    SYS2[plan de campaña<br/>F8, §17] -.nivel sistema.-> RUN
```

Cada alimentador cabe en memoria (~2.800 clientes, ~1.700 postes) y es la
**clave de partición y de paralelización** (`ProcessPoolExecutor`). El
**procesamiento incremental por hash** evita recomputar lo que no cambió (§2.3).
La detección de transferencias y la priorización son pasos **a nivel de
sistema** (un único presupuesto sobre todos los candidatos).

## 3. Pipeline por alimentador (fases)

```mermaid
flowchart LR
    IN[(BRONZE)] --> F2[F2 Topología<br/>grafo + zonas + calidad]
    F2 --> F3[F3 Eléctrico<br/>P/Q/S/I + curvas]
    F3 --> F5[F5 Balance<br/>PNT + cargabilidad]
    F5 --> F4[F4 Flujo de potencia<br/>BFS + OpenDSS]
    F4 --> F6[F6 Estimación de estado<br/>WLS + reconciliación]
    F6 --> F7[F7 Riesgo<br/>PU + no superv. + SHAP]
    F7 --> OUT[(GOLD)]
    OUT --> F8[F8 Priorización<br/>MILP + ruteo]
```

| Fase | Módulo | Entrada → Salida |
|---|---|---|
| F2 | `topology` | segments/sites → grafo, zonas, `data_quality_findings` |
| F3 | `electrical` | consumo → P/Q/S/I, factor de pérdidas |
| F5 | `pipeline.balance` | + AP + técnicas → `feeder_balance`, `transformer_loadability` |
| F4 | `powerflow` | grafo + carga → `powerflow_results` (validado vs OpenDSS) |
| F6 | `stateest` | pseudo-medidas → `zone_state_estimation` (carga no contabilizada) |
| F7 | `ml` | features → `customer_risk` (score calibrado + razones SHAP) |
| F8 | `prioritization` | GOLD → `inspection_plan`, rankings, `campaign_summary` |

## 4. Dependencias entre módulos

```mermaid
flowchart TD
    config --> domain
    config --> lakehouse
    domain --> electrical
    domain --> topology
    electrical --> pipeline
    topology --> pipeline
    topology --> powerflow
    powerflow --> pipeline
    stateest --> pipeline
    ml --> pipeline
    pipeline --> prioritization
    lakehouse --> pipeline
    lakehouse --> io
    synth --> lakehouse
    pipeline --> dashboard
    pipeline --> io
```

El **dominio** (jerarquía poste/puesto/unidad §5.2 y fórmulas §9.2) no depende de
nada externo y es 100% testeable. Los motores de ejecución (multiprocessing,
DuckDB, OpenDSS) son intercambiables: la lógica de dominio no los conoce.

## 5. Estrategia por niveles de profundidad (§2.4)

| Nivel | Alcance | Método | Estado |
|---|---|---|---|
| N1 tamizaje | todos los alimentadores | balance + BFS 3 escenarios | ✅ motor propio |
| N2 detalle | decil superior de PNT | OpenDSS desbalanceado | ✅ exportador |
| N3 forense | campañas | QSTS + Monte Carlo + DSSE | parcial (DSSE ✅) |

## 6. Stack tecnológico

`duckdb`, `pyarrow`, `pandas`, `numpy` · `pydantic`, `typer`, `loguru` ·
`rustworkx` (topología) · `OpenDSSDirect.py` (flujo) · `scikit-learn`,
`lightgbm`, `pyod`, `ruptures`, `shap` (ML) · `ortools`, `HDBSCAN`
(optimización/ruteo) · `geopandas`/`pyogrio`/GDAL (FGDB, sin `arcpy`) ·
`streamlit`/`plotly` (dashboard) · `pytest`/`hypothesis` (pruebas).

Ver la **[Referencia de módulos y funciones](REFERENCIA.md)** y el
**[Análisis de brechas](BRECHAS.md)**.
