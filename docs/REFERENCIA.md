# Referencia de módulos y funciones

Detalle de todo el programa. **133 funciones/clases públicas, 100 % con
docstring.** El código fuente está documentado línea a línea; aquí el índice
navegable. Para el esquema de datos usa `lossan schema inspect`.

Paquete: `src/lossan/` · CLI: `lossan` · Cobertura de pruebas: `tests/` (51 tests).

---

## CLI — `lossan.cli`
`lossan <comando> --help` para detalle de cada uno.

| Comando | Qué hace |
|---|---|
| `generate` | Genera el universo sintético en BRONZE |
| `run` | Ejecuta el pipeline (`--level full\|n1`, incremental por hash) |
| `bench` | Prueba de escala: genera N alimentadores y extrapola a 960 (§2.1) |
| `status` | Resumen del avance por alimentador desde GOLD |
| `feeder-report <F>` | Elementos conectados por traza + desglose de pérdidas |
| `dashboard` | Lanza el dashboard web (Streamlit) |
| `schema inspect` | Imprime el esquema canónico de cada entidad |
| `schema template` | Genera archivo para MODELAR el mapeo del SIG |
| `fgdb-layers <gdb>` | Lista las capas de una File Geodatabase |
| `ingest-fgdb <gdb>` | Ingiere la red de una FGDB a BRONZE (§2.5) |
| `ingest-consumption <csv>` | Ingiere el consumo histórico a BRONZE |
| `ingest-header <csv>` | Ingiere la cabecera a BRONZE |
| `export-sample` | Datos de prueba (CSV + GPKG + FileGDB) |
| `export-results` | Capas de resultados para ArcGIS (§18) |
| `data-templates` | Plantillas vacías (CSV + Excel) por dato requerido |

---

## Configuración — `lossan.config`
_Carga de `config/*.yaml`; nada de negocio en el código (§22.13)._
- `config_dir()` — directorio de configuración (`$LOSSAN_CONFIG_DIR` o `<repo>/config`).
- `Config` — acceso cacheado a scale/budget/economics/electrical/thresholds/streetlight/conductors/rules.
- `load_config()`, `reset_cache()` — instancia cacheada y limpieza (tests).

## Dominio

### `lossan.domain.enums`
Enumeraciones: `SiteKind`, `UnitKind`, **`BankConfig`** (single/wye/delta/open_delta/delta_4wire/independent), `Phase`, `TariffClass`, `LoadabilityClass`, `Construction`.

### `lossan.domain.bank` — §5.2 agregación de bancos
- `UnitPlate(sn_kva, p0_kw, pk_kw, voltage_ln)` — placa de una unidad.
- `bank_capacity(config, units, open_delta_factor)` — capacidad 3φ + excedente monofásico (delta abierto = √3·S).
- `bank_no_load_losses(units)` — `P0 = Σ P0_unidad` (permanente).
- `bank_load_losses_at(units, loads)` — `Pk` referido a la carga real de cada unidad.
- `evaluate_bank(config, units)` — `BankResult` (capacidad, excedente, P0 total).
- `validate_bank_config(config, units)` — reglas P03/P04.

### `lossan.domain.models` — modelo canónico `pydantic` (§4, §5)
`Pole, Site, TransformerUnitModel, Customer, ConsumptionRecord, Segment, Streetlight, HeaderMeter, SwitchingDevice, SwitchingEvent, ProtectionZone, FieldInspection`. `CANONICAL_MODELS` mapea entidad→modelo.

## Eléctrico — `lossan.electrical.formulas` — §9.2 (todas las fórmulas)
Demanda/pérdidas: `mean_power_kw`, `load_factor`, **`loss_factor`** (Buller–Woodrow, verifica FC²≤FP≤FC), `velander_dmax_kw`, `coincidence_factor`, `diversified_demand_kw`.
P-Q-S: `pf_from_kwh_kvarh`, `tanphi_from_kwh_kvarh`, `q_from_p`, `s_from_p_pf`, `s_from_pq`, **`aggregate_pqs`** (nunca suma S).
Corriente: `current_3ph`, `current_1ph_2wire`, `current_1ph_3wire`, **`neutral_current`** (obligatoria).
Pérdidas: `resistance_at_temp`, `conductor_loss_3ph_balanced/unbalanced`, `conductor_loss_1ph_2wire/3wire`, `energy_loss_kwh`, `transformer_power_loss_kw`, `transformer_energy_loss_kwh`, `voltage_drop`.

## Topología (F2)

### `lossan.topology.graph` — grafo `rustworkx` + trazas (§6)
- `FeederGraph.build(feeder_id, segments, sites)` — construye el grafo dirigido.
- `.trace_downstream / .trace_upstream / .path_to_source / .subtree_load / .branch_decomposition`.
- `.validate()` — radialidad, islas, multi-alimentación.

### `lossan.topology.zones` — zonas de protección (§7.5)
- `build_protection_zones(fg, devices, sites, customers)` → `(zones_df, node_to_zone)`.

### `lossan.topology.dynamic` — topología dinámica (§7)
- `reconstruct_topology_versions(events, start, end)` — versiones por intervalo.
- `infer_transfers(header_wide)` — transferencias entre alimentadores (§7.4).

### `lossan.topology.quality` — reglas R01-R25 (§8)
- `run_quality_rules(...)` — hallazgos con `rule_id/severity/evidence/confidence/suggested_value`.

## Flujo de potencia (F4)

### `lossan.powerflow.sweep` — motor propio
- `RadialNetwork`, `SweepResult`, **`solve_bfs(net)`** (backward-forward sweep), `network_from_feeder(...)`.

### `lossan.powerflow.opendss_export`
- `export_dss(net, path)` — `.dss` (Line/Load), `transformer_dss(...)` (Transformer por unidad con conexión de banco), `solve_with_opendss(path)`.

### `lossan.powerflow.validate`
- `compare_engines(net)` — sweep vs OpenDSS dentro de tolerancia (§11).
- `canonical_radial_case()`, `power_balance_error(net)`.

## Estimación de estado (F6) — `lossan.stateest.estimate` (§14.3)
- `pseudo_measurements(site_monthly)` — pseudo-medidas con incertidumbre histórica.
- `run_wls(z, sigma, measured_total)` — WLS anclado a cabecera; residuos normalizados, chi², LNR.
- `reconcile_by_zone(...)` — carga no contabilizada por zona (proporcional al residuo).

## ML de riesgo (F7)

### `lossan.ml.label_mining` — mecanismos M1-M8 (§15.2)
- `m1_drop_recovery, m2_jump_after_intervention, m4_zero_active, m5_level_break, m6_pf_collapse, m7_peer_divergence, m8_intra_site_dispersion`.
- `mine_labels(consumption, customers)` — ejecuta todos; `validate_against_confirmed(mined, theft)` — recall (§22.8).

### `lossan.ml.features` — `build_features(consumption, customers, cutoff)` (anti-fuga temporal).

### `lossan.ml.pu` — PU learning (§15.1)
- `elkan_noto`, `bagging_pu`, `spies`, `fit_pu(X, s, method)`.

### `lossan.ml.risk`
- `train_risk_model(...)` — ensamble PU + no supervisado + isotónica + SHAP.
- `precision_at_k(...)`, `energy_recoverable_at_k(...)`.

## Priorización (F8)

- `economics.build_candidates(...)` — beneficio/costo/ROI por **puesto** (§17.1).
- `optimize.knapsack_optimize` (MILP OR-Tools), `greedy_roi`, `two_stage_allocation`, `exploration_reserve` (§17.4), `allocation_curve`.
- `routing.cluster_and_route(...)` — HDBSCAN + secuencia + órdenes de trabajo (§17.5).
- `plan.build_inspection_plan(root)` — plan + rankings + resumen (Precision@k).

## Pipeline (orquestación)
- `pipeline.balance.analyze_feeder(tables)` — F3/F5 (ENS incluida, §7.6).
- `pipeline.technical` — `transformer_site_energy_loss_kwh`, `secondary_conductor_loss_kwh`.
- `pipeline.reconciliation.reconcile_feeder / reconcile_all` — informe P/Q (§9.3).
- `pipeline.transfer_credit.apply_transfer_credits(lake, cfg)` — acredita transferencias (§7.3).
- `pipeline.analyze.analyze_feeder_full(tables, level)` — F2+F3/F5(+F4+F6+F7 si `full`).
- `pipeline.runner.run(root, level, ...)` — orquesta + incremental + transferencias + reconciliación; `list_feeders`.
- `pipeline.prioritization_step.build_plan_and_mark(lake, cfg)` — F8 + marca de avance.

## Topología dinámica (§7) — `lossan.topology.dynamic`
- `infer_transfers(header_wide)`, `quantify_transfers(header_wide, transfers)` — detección y cuantificación (§7.4).
- `estimate_ens_kwh(events)` — energía no suministrada (§7.6).
- `reconstruct_topology_versions(events, start, end)` — versiones por intervalo (§7.3).

## Lakehouse — `lossan.lakehouse.storage` (§2.2)
- `Lakehouse(root)` — rutas Bronze/Silver/Gold, `write_partition`, `read_entity`, `query` (DuckDB), estado incremental (`needs_recompute`, `mark_done`).
- `feeder_input_hash(*frames)` — hash determinístico por alimentador.

## Generador sintético — `lossan.synth.generator`
- `SyntheticGenerator(cfg)` — universo a escala (jerarquía, bancos, hurtos inyectados).
- `generate_universe(root, cfg)` — escribe BRONZE y devuelve conteos.

## Entrada/Salida — `lossan.io`
- `fgdb.ingest_fgdb / list_layers / read_layer` — FGDB con GDAL/OpenFileGDB (§2.5).
- `consumption.ingest_consumption / ingest_header` — CSV/Parquet/Excel → BRONZE.
- `export.export_sample / export_results / build_geodataframes` — GPKG/FGDB.
- `templates.build_templates` — plantillas vacías por dato requerido.

---

_Generado a partir de la introspección del paquete; el docstring de cada función
es la fuente de verdad. Regenera el detalle con `lossan schema inspect` y con la
ayuda de cada comando._
