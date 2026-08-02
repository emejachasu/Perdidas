# Requerimiento v3 — Índice de módulos y trazabilidad

Este documento resume el requerimiento v3 y traza cada sección con su estado de
implementación en el código. La especificación completa es la fuente de verdad
del proyecto.

## Objetivo
Plataforma analítica en Python que separa pérdidas técnicas de no técnicas (PNT)
por alimentador, zona de protección, ramal y puesto de transformación, detecta
inconsistencias del modelo, balancea puestos sin medición, calcula correctamente
P/Q/S/I, clasifica cargabilidad y prioriza inspección de campo bajo restricción
presupuestal (4 M USD), usando ML robusto a etiquetas incompletas (PU learning).

## Trazabilidad de módulos

| § | Módulo | Estado | Ubicación |
|---|---|---|---|
| §2 | Lakehouse Bronze/Silver/Gold + DuckDB + hash incremental | F0 ✅ | `lakehouse/storage.py`, `pipeline/runner.py` |
| §4-§5 | Modelo canónico + jerarquía Poste→Puesto→Unidad | ✅ | `domain/models.py`, `domain/bank.py` |
| §5.2 | Agregación de capacidad y pérdidas de banco | ✅ | `domain/bank.py` |
| §6 | Topología y trazas (`rustworkx`) | ✅ F2 | `topology/graph.py` |
| §7 | Topología dinámica, zonas de protección, transferencias | ✅ F2 (ENS 🔜 F5) | `topology/zones.py`, `topology/dynamic.py` |
| §8 | Calidad de datos R01–R25 (motor por YAML) | ✅ F2 | `topology/quality.py`, `config/rules.yaml` |
| §9 | P/Q/S/I y pérdidas (todas las fórmulas) | ✅ | `electrical/formulas.py` |
| §10 | Alumbrado público | ✅ | `pipeline/balance.py` |
| §11 | Flujo de potencia propio + OpenDSS + validación cruzada | ✅ F4 | `powerflow/` |
| §12 | Pérdidas técnicas | ✅ | `pipeline/technical.py` |
| §13 | Balance jerárquico y PNT | ✅ | `pipeline/balance.py` |
| §14 | Cargabilidad + desbalance + ramales | Cargabilidad ✅ / resto 🔜 F6 | `pipeline/balance.py` |
| §15 | PU learning + minería de etiquetas + SHAP + Precision@k | ✅ F7 | `ml/` |
| §16 | Agregación multinivel del riesgo | Parcial (score+zona) 🔜 F8 | `ml/risk.py` |
| §17 | Priorización 4 M USD + OR-Tools + ruteo | 🔜 F8 | `config/budget.yaml` |
| §18 | Salidas, dashboard, KPIs | Dashboard ✅ | `dashboard/app.py` |
| §19 | Validación y pruebas | Parcial ✅ | `tests/` |
| §23 | Persistencia de bajo costo + `field_inspections` | Esquema ✅ | `domain/models.py` |

## Decisiones metodológicas intercambiables (por configuración)
Conforme al Anexo C, cuando una decisión admite alternativas válidas
(asignación de PNT, variante de PU learning, detección de transferencias,
inferencia de banco) se implementan como estrategias seleccionables por
configuración. La base actual deja los puntos de extensión preparados
(`config/thresholds.yaml`, `config/electrical.yaml`).
