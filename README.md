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
| Balance jerárquico + PNT + cargabilidad por configuración de banco | ✅ (F0) | §13, §14.1 |
| Alumbrado público como término explícito del balance | ✅ (agregado) | §10 |
| Esquema `field_inspections` (captura de campo) | ✅ | §23.1 |
| **Dashboard web por alimentador** (Streamlit + Plotly) | ✅ | §18 |
| Suite de pruebas (fórmulas, bancos, propiedades, end-to-end) | ✅ | §19 |
| Topología `rustworkx`, zonas de protección, topología dinámica | 🔜 F2 | §6, §7 |
| Flujo de potencia propio + OpenDSS + validación IEEE | 🔜 F4 | §11 |
| Estimación de estado / ramales sin medición | 🔜 F6 | §14.3 |
| PU learning + minería de etiquetas + SHAP | 🔜 F7 | §15 |
| Priorización 4 M USD + OR-Tools + ruteo | 🔜 F8 | §17 |

El dashboard muestra las fases planificadas como *roadmap* para que el avance
por alimentador refleje el estado real del pipeline.

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

# 4) Abrir el dashboard web por alimentador
lossan dashboard        # http://localhost:8501
```

Cambia la escala en `config/scale.yaml` (`active_profile: demo | full`), o
`lossan generate --profile full` para el universo objetivo (960 alimentadores).

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
  pipeline/
    technical.py        # física de pérdidas técnicas (compartida)
    balance.py          # balance jerárquico, PNT, cargabilidad, riesgo
    runner.py           # orquestación por alimentador + avance
  dashboard/
    app.py              # dashboard web por alimentador
tests/                  # fórmulas, bancos, propiedades (hypothesis), end-to-end
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
