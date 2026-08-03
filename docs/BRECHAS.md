# Análisis de brechas frente al Requerimiento v3

Estado honesto de cobertura. ✅ Completo · 🟨 Parcial · ⬜ Pendiente.
El objetivo del proyecto (separar pérdidas técnicas de PNT, priorizar campo) está
**operativo end-to-end**; lo pendiente es profundización y robustez de escala.

## Resumen

| Área | Estado |
|---|---|
| Fundacional, dominio, fórmulas, topología, balance, riesgo, priorización, I/O | ✅ |
| Profundización numérica (3φ desbalanceado, Monte Carlo, IEEE) | 🟨 / ⬜ |
| Escala 960 real, orquestador Dagster, capa SILVER materializada | 🟨 / ⬜ |
| Reportes PDF, publicación PostGIS, simbología .lyrx | ⬜ |

---

## Detalle por módulo

> **Actualización:** implementadas y probadas seis brechas prioritarias:
> reconciliación P/Q (§9.3), transferencias + ENS (§7.3/§7.6), escala N1 (§2.1),
> **flujo 3φ desbalanceado validado vs OpenDSS (§11)**, **reportes PDF + ficha de
> inspección (§18)** y **orquestador Dagster (§2.3)**.

### ✅ Completo (funcional y probado)
- **§9.3** informe de reconciliación de P y Q (corregido vs actual, por causa).
- **§7.6** ENS descontada del balance; **§7.3/§7.4** transferencias cuantificadas y acreditadas.
- **§2.1/§2.4** prueba de escala N1 + niveles de profundidad (`lossan run --level n1`, `lossan bench`).
- **§11** flujo **3φ desbalanceado** (matriz 3×3, corriente de neutro) validado vs OpenDSS (dif. < 0,02 %).
- **§18** reporte ejecutivo por alimentador, consolidado regional y **ficha de inspección por poste** (HTML/PDF).
- **§2.3** orquestador **Dagster** con assets particionados por alimentador (incremental por hash).
- **F0** lakehouse Bronze/Gold + DuckDB + incremental por hash + generador sintético.
- **§5** jerarquía poste/puesto/unidad y **agregación de banco** (delta abierto, desiguales, P0/Pk por unidad) con tests.
- **§9** todas las fórmulas P/Q/S/I con test de caso manual y propiedades.
- **§6** grafo por alimentador y trazas (downstream/upstream/path/subtree/branch).
- **§7.5** zonas de protección; **§7.4** inferencia de transferencias.
- **§8** reglas R01-R25 (motor por YAML) con valor sugerido.
- **§11** motor propio BFS + exportador OpenDSS + **validación cruzada** (dif. < 0,01 %).
- **§12/§13** pérdidas técnicas por unidad, balance jerárquico y PNT, AP como término.
- **§14.1/§14.3** cargabilidad por banco y **estimación de estado WLS** (chi²/LNR/reconciliación por zona).
- **§15** minería M1-M8 + PU (Elkan-Noto/Bagging/spies) + no supervisado + isotónica + SHAP + Precision@k.
- **§17** priorización MILP (OR-Tools) + dos etapas + reserva de exploración + clustering + ruteo + rankings.
- **§18** dashboard por alimentador; **§2.5** I/O FGDB sin arcpy; **§23.1** esquema `field_inspections`.

### 🟨 Parcial (implementado con simplificación)
| Ref | Qué falta para completarlo | Impacto |
|---|---|---|
| §7.3 | Transferencias ya acreditadas al balance; falta afinarlo **por intervalo de topología** (hoy a nivel de periodo) | Menor precisión temporal |
| §8.2/§8.3 | Falta el **clasificador de auto-consistencia** (LightGBM predice el conductor por contexto) y el **índice de confiabilidad 0-100** por alimentador/zona | Menos detección de atributos mal cargados |
| §9.4 | Curvas de carga por **clustering** (k-means/DTW); hoy se usa un FC representativo | Menor precisión horaria (afecta N2/N3) |
| §10 | **Efemérides** (astral) para horas de AP por latitud/mes; anomalías de AP (day-burning, conexión ilegal, tecnología declarada≠instalada) | AP con horas fijas; sin categoría de hurto en AP |
| §11 | Motor 3φ desbalanceado ✅ (matriz 3×3 por secuencia); falta reproducir **IEEE 13/34/123** formales (hoy validado vs OpenDSS en caso desbalanceado propio) | Trazabilidad IEEE |
| §14.2 | Motor 3φ ya da corriente de neutro y desbalance; falta cablearlo al **puesto** con el mapeo unidad→fase | Beneficio de rebalanceo no cuantificado aún |
| §16 | Composición explícita riesgo unidad→puesto→zona (f/g/h) en una sola tabla | Ranking multinivel menos afinado |
| §17.5 | Ruteo por **vecino más cercano**; falta VRP OR-Tools con ventanas de tiempo | Rutas subóptimas |
| SILVER | La capa **SILVER** canónica no se materializa (se lee BRONZE directo) | Menos trazabilidad intermedia |

### ⬜ Pendiente (no implementado)
| Ref | Elemento | Prioridad sugerida |
|---|---|---|
| §12 | **Monte Carlo P10/P50/P90** (propagación de incertidumbre) | 🟡 Media |
| §11/§19 | Reproducción **IEEE 13/34/123** formales con fallo de CI (motor 3φ ya validado vs OpenDSS) | 🟡 Media |
| §14.1 | **Envejecimiento térmico** IEEE C57.91 / IEC 60076-7 | 🟢 Baja |
| §15.4 | **IPW** (corrección de sesgo de selección por propensidad de inspección) | 🟡 Media |
| §18/§23 | Publicación a **PostGIS** y simbología **.lyrx** | 🟢 Baja |
| §23.1 | Integración de captura con **Survey123/Field Maps** (externo a este repo) | 🟡 Media |

---

## Criterios de aceptación (§22)

| # | Criterio | Estado |
|---|---|---|
| 1 | Procesa el universo dentro de §2.3 | ✅ N1 extrapola a 960 < 8 h; falta corrida real 960 |
| 2 | Reproduce IEEE 13/34/123 | 🟨 motor 3φ validado vs OpenDSS; faltan los casos IEEE formales |
| 3 | Balance cierra con residuo < 0,5 % | ✅ (12/12) |
| 4 | Fórmulas §9.2 con test de caso manual | ✅ |
| 5 | Capacidad/pérdidas por unidad y banco, con tests | ✅ |
| 6 | Informe de reconciliación de P y Q | ✅ (`pq_reconciliation` + tablero) |
| 7 | R01-R25 + P01-P12 como capa geoespacial navegable | ✅ (capa + suggested_value) |
| 8 | Minería validada contra inspecciones | ✅ (recall reportado) |
| 9 | Evaluación por Precision@k, no AUC-ROC | ✅ |
| 10 | Cada punto con razones explicables | ✅ (SHAP top-3) |
| 11 | Plan respeta presupuesto + reserva + ROI | ✅ |
| 12 | Reejecución reproducible | ✅ (hash + seeds) |
| 13 | Ningún valor de negocio en el código | ✅ (todo en `config/`) |

---

## Recomendación de siguientes pasos (orden de valor)

Seis brechas prioritarias ya están **hechas** (§9.3, §7.3/§7.6, §2.1, §11 3φ,
§18, §2.3). Siguientes por valor:

1. Cargar los **casos IEEE 13/34/123 formales** al comparador 3φ ya existente (§11/§19).
2. **%Desbalance por puesto** con el mapeo unidad→fase y beneficio de rebalanceo (§14.2).
3. **Monte Carlo P10/P50/P90** e **IPW** para robustez estadística (§12/§15.4).
4. **Efemérides y anomalías de AP** (§10); índice de confiabilidad 0-100 (§8.3).
5. Publicación **PostGIS** + simbología **.lyrx** (§18).

Nada de lo pendiente invalida el flujo actual: son profundizaciones sobre una
base operativa y probada (51 tests en verde).
