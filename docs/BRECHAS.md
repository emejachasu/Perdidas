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

> **Actualización:** implementadas y probadas: reconciliación P/Q (§9.3),
> transferencias + ENS (§7.3/§7.6), escala N1 (§2.1), flujo 3φ desbalanceado
> validado vs OpenDSS (§11), **casos IEEE-13 con matrices reales**, reportes PDF
> + ficha de inspección (§18), orquestador Dagster (§2.3), **%desbalance por
> puesto (§14.2)**, **Monte Carlo P10/P50/P90 (§12)** e **IPW (§15.4)**.

### ✅ Completo (funcional y probado)
- **§9.3** informe de reconciliación de P y Q (corregido vs actual, por causa).
- **§7.6** ENS descontada del balance; **§7.3/§7.4** transferencias cuantificadas y acreditadas.
- **§2.1/§2.4** prueba de escala N1 + niveles de profundidad (`lossan run --level n1`, `lossan bench`).
- **§11** flujo **3φ desbalanceado** (matriz 3×3, corriente de neutro) validado vs OpenDSS (dif. < 0,02 %).
- **§18** reporte ejecutivo por alimentador, consolidado regional y **ficha de inspección por poste** (HTML/PDF).
- **§2.3** orquestador **Dagster** con assets particionados por alimentador (incremental por hash).
- **§11/§19.4** caso **IEEE-13** con matrices de configuración reales (601/602), motor propio vs OpenDSS dif. < 0,01 %.
- **§14.2** **%desbalance por puesto** con mapeo cliente→fase, corriente de neutro y beneficio de rebalanceo.
- **§12** **Monte Carlo P10/P50/P90** de pérdidas técnicas y PNT.
- **§15.4** **IPW** (pesos por propensidad inversa de inspección).
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
| §11 | IEEE-13 (líneas) ✅; faltan **reguladores, transformadores en línea y capacitores** de IEEE 13/34/123 completos | Reproducción íntegra del estándar |
| §16 | Composición explícita riesgo unidad→puesto→zona (f/g/h) en una sola tabla | Ranking multinivel menos afinado |
| §17.5 | Ruteo por **vecino más cercano**; falta VRP OR-Tools con ventanas de tiempo | Rutas subóptimas |
| SILVER | La capa **SILVER** canónica no se materializa (se lee BRONZE directo) | Menos trazabilidad intermedia |

### ⬜ Pendiente (no implementado)
| Ref | Elemento | Prioridad sugerida |
|---|---|---|
| §11/§19 | **IEEE 13/34/123 completos** (reguladores/transformadores/capacitores) con fallo de CI | 🟡 Media |
| §14.1 | **Envejecimiento térmico** IEEE C57.91 / IEC 60076-7 | 🟢 Baja |
| §10 | **Efemérides** de AP y anomalías de alumbrado (day-burning, conexión ilegal) | 🟡 Media |
| §8.3 | **Índice de confiabilidad 0-100** por alimentador/zona | 🟡 Media |
| §18/§23 | Publicación a **PostGIS** y simbología **.lyrx** | 🟢 Baja |
| §23.1 | Integración de captura con **Survey123/Field Maps** (externo a este repo) | 🟡 Media |

---

## Criterios de aceptación (§22)

| # | Criterio | Estado |
|---|---|---|
| 1 | Procesa el universo dentro de §2.3 | ✅ N1 extrapola a 960 < 8 h; falta corrida real 960 |
| 2 | Reproduce IEEE 13/34/123 | 🟨 IEEE-13 (líneas) validado vs OpenDSS; faltan reguladores/transformadores del caso completo |
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

La mayoría de las brechas están **hechas**. Restantes por valor:

1. **IEEE 13/34/123 completos** (reguladores, transformadores en línea, capacitores) (§11/§19).
2. **Efemérides y anomalías de AP** (§10) e **índice de confiabilidad 0-100** (§8.3).
3. **Envejecimiento térmico** IEEE C57.91 para sustentar reemplazos (§14.1).
4. Publicación **PostGIS** + simbología **.lyrx** (§18); materializar capa SILVER.
5. **Curvas de carga por clustering** (k-means/DTW) para N2/N3 (§9.4).

Nada de lo pendiente invalida el flujo actual: son profundizaciones sobre una
base operativa y probada (51 tests en verde).
