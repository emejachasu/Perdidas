# Datos requeridos — inventario completo y priorizado

Lista exhaustiva de los datos de entrada, su origen, formato, campos y
prioridad. Llévala a tus equipos de SIG, Comercial y Operación.

**Prioridad:**
🔴 **Imprescindible** (sin esto no hay resultado) ·
🟡 **Recomendado** (mejora sustancial) ·
🟢 **Opcional** (eleva el resultado, Anexo B).

---

## A. Del SIG / GIS (File Geodatabase)  → `lossan ingest-fgdb`

| # | Dato (capa) | Prioridad | Campos mínimos | Por qué / consecuencia si falta |
|---|---|---|---|---|
| A1 | **Tramos / conductores** (`segments`) | 🔴 | node_from, node_to, conductor_code, fases, tensión, (geometría de línea) | Definen la **conectividad** y las pérdidas técnicas. Sin ellos no hay topología ni balance. |
| A2 | **Puestos** (`sites`) | 🔴 | site_id, tipo (transformación/cliente/AP), pole_id, node_id | Agrupación funcional; unidad de balance y de visita. |
| A3 | **Unidades de transformador** (`transformer_units`) | 🔴 | unit_id, site_id, kVA nominal (Sn) | Capacidad y pérdidas del puesto (§5.2). |
| A4 | **Clientes / acometidas** (`customers`) | 🔴 | customer_unit_id, site_id, clase tarifaria, (geometría) | Asignación por traza y agregación de carga. |
| A5 | **Postes** (`poles`) | 🟡 | pole_id, geometría de punto | Unidad de intervención y ruteo; concilia inventario. |
| A6 | **Config. de banco por puesto** (`bank_config`) | 🟡 | single/wye/delta/open_delta/delta_4wire | Evita inferirla; capacidad correcta del banco (§5.2). |
| A7 | **P0 / Pk / %Z por unidad** | 🟡 | p0_kw, pk_kw, z_pct | Pérdidas reales de transformador; si faltan se usa catálogo por kVA. |
| A8 | **Fase por unidad/cliente** | 🟡 | phase | Desbalance real, corriente de neutro, beneficio de rebalanceo. |
| A9 | **Luminarias / AP** (`streetlights`) | 🟡 | streetlight_id, transformer_site_id, tecnología, potencia | AP no medido = consumo no facturado; si se ignora infla la PNT. |
| A10 | **Dispositivos de maniobra** (`switching_devices`) | 🟡 | device_id, node_id, tipo, estado normal (NA/NC) | Zonas de protección (ramal) y topología dinámica. |
| A11 | Geometría de estructuras/postería | 🟢 | vanos, disposición | Impedancias por Carson (N3). |

## B. Del Sistema Comercial  → `lossan ingest-consumption` / `ingest-header`

| # | Dato | Prioridad | Campos mínimos | Por qué / consecuencia si falta |
|---|---|---|---|---|
| B1 | **Consumo histórico** (`consumption`) | 🔴 | customer_unit_id, feeder_id, year_month, **kwh** | Núcleo de balance y detección de hurto. Ver [HISTORIA.md](HISTORIA.md): 36 m recomendado. |
| B2 | **kVArh por cliente** | 🟡 | kvarh | cosφ real por cliente (método preferente §9.2) y mecanismo M6. |
| B3 | **Marca de lectura estimada** | 🟡 | estimated (bool) | No imputar en silencio; reporta % de energía estimada (§13). |
| B4 | **Medidor de cabecera** (`header_meters`) | 🔴 | feeder_id, year_month, kwh, (kvarh) | Sin la energía de cabecera el balance **no existe**. |
| B5 | **Curvas horarias de cabecera** | 🟢 | perfil horario | Calibra FC, FP y cosφ reales (Anexo B). |
| B6 | **Refacturaciones / ajustes** | 🟡 | energía recuperada, fecha | Etiquetas de hurto *de facto* (mecanismo M3, muy confiable). |
| B7 | **Clase tarifaria y carga instalada** | 🟡 | tariff_class, installed_load_kw | Grupos par, Velander, coherencia consumo/carga. |
| B8 | **Órdenes de suspensión / estado del servicio** | 🟢 | activo/suspendido, fechas | Distingue "cero legítimo" de anomalía (M4). |

## C. De Operación / SCADA / DMS / ADMS

| # | Dato | Prioridad | Campos mínimos | Por qué / consecuencia si falta |
|---|---|---|---|---|
| C1 | **Log de conmutación** | 🟡 | device_id, timestamp, estado_previo/nuevo, motivo | El de **mayor impacto** tras el consumo: sin él, el balance de una fracción de alimentadores no cierra (transferencias). |
| C2 | Ajustes de protección | 🟢 | por dispositivo | Coherencia de zonas. |
| C3 | Interrupciones (para ENS) | 🟡 | zona, duración | La energía no suministrada no es pérdida; si no se descuenta, aparece como tal. |

## D. Catálogos y parámetros (una vez)

| # | Dato | Prioridad | Dónde | Por qué |
|---|---|---|---|---|
| D1 | **Catálogo de conductores** | 🔴 | `config/conductors.yaml` | R, X, ampacidad por código. Ya provisto; ajústalo a tus conductores. |
| D2 | **Catálogo P0/Pk por kVA/tipo/norma** | 🟡 | config | Respaldo cuando falta la placa (A7). |
| D3 | **Tarifa USD/kWh, costos de visita, presupuesto** | 🔴 | `config/budget.yaml` | Priorización económica (§17). |
| D4 | Parámetros de calibración (k, cosφ, Velander, A/B, umbrales) | 🟡 | `config/electrical.yaml`, `thresholds.yaml` | Ver [TUNING.md](TUNING.md). Tienen default documentado. |

## E. De Campo (retorno de campaña)  → esquema `field_inspections`

| # | Dato | Prioridad | Campos mínimos | Por qué |
|---|---|---|---|---|
| E1 | **Resultado de inspecciones** | 🔴 (para mejorar) | site_id, fecha, hallazgo(sí/no), tipo, energía recuperada, costo real | Sin el retorno el modelo **nunca mejora** y la reserva de exploración pierde sentido (§23.1). |
| E2 | **Inspecciones sin hallazgo** | 🟡 | (las mismas) | Son los **negativos confiables** que necesita el PU learning. |
| E3 | Fotos / evidencia | 🟢 | URIs | Trazabilidad. Captura con Survey123/Field Maps (§23). |

---

## Mínimo para arrancar (MVP)

Con **A1, A2, A3, A4 (SIG) + B1, B4 (consumo y cabecera) + D1, D3** ya se obtiene:
balance por alimentador, pérdidas técnicas, cargabilidad por puesto, PNT y un
ranking de riesgo inicial. Todo lo demás **mejora** la precisión y el retorno.

## Orden de impacto si tienes que priorizar la consecución de datos

1. **Consumo histórico + cabecera** (B1, B4) — sin esto no hay nada.
2. **Topología: tramos + puestos + unidades + clientes** (A1–A4).
3. **Log de conmutación** (C1) — cierra los balances que hoy no cierran.
4. **kVArh + refacturaciones** (B2, B6) — potencian la detección de hurto.
5. **AP conciliado** (A9) — evita inflar la PNT.
6. **Retorno de campo** (E1, E2) — hace que el modelo mejore campaña a campaña.

---

## Cómo entregar cada dato

- **SIG:** una File Geodatabase (`.gdb`). Modela el mapeo en
  `config/schema_mapping.yaml` (o genera la plantilla con
  `lossan schema template`). Ver [DATA_MODEL.md](DATA_MODEL.md).
- **Comercial / SCADA:** CSV/Parquet/Excel con las columnas indicadas.
  `lossan ingest-consumption`, `lossan ingest-header`.
- **Formatos, tipos y obligatoriedad de cada campo:** `lossan schema inspect`.
