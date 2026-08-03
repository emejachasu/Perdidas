# Modelo de datos de entrada (SIG) y análisis de conectividad

Este documento es la referencia para **modelar los datos de entrada** de tus
bases SIG y entender cómo se identifican los elementos conectados por
alimentador y cómo eso produce las pérdidas.

Para modelar tu SIG hay dos archivos:
- **`config/schema_mapping.yaml`** — mapeo activo que usa `lossan ingest-fgdb`.
- **Plantilla generable**: `lossan schema template --out mi_modelo.yaml` crea un
  archivo con **todas** las entidades y campos canónicos, su **tipo** y si son
  **[req]/[opc]**, para que lo rellenes con los nombres de tu FGDB.

`lossan schema inspect` imprime el esquema canónico vigente (fuente de verdad:
los modelos `pydantic` en `src/lossan/domain/models.py`).

---

## 1. Diccionario de datos canónico

Leyenda: **R** requerido · **O** opcional. Todas las entidades espaciales
llevan además `feeder_id` (declarado) y, tras la traza, `feeder_id_traced`.

### Poste (`poles`) — activo físico, unidad de intervención (§5.4)
| Campo | Tipo | R/O | Descripción |
|---|---|---|---|
| pole_id | str | R | Identificador único del poste |
| x, y | float | R | Coordenadas (de la geometría de punto) |
| pole_type | str | O | Tipo/material |
| height_m | float | O | Altura |

### Puesto (`sites`) — agrupación funcional en una ubicación (§5.1)
| Campo | Tipo | R/O | Descripción |
|---|---|---|---|
| site_id | str | R | Id del puesto |
| pole_id | str | O | Poste que lo aloja |
| kind | enum | R | transformer / customer / switching / metering / streetlight |
| bank_config | enum | O | single / wye_closed / delta_closed / open_delta / delta_4wire / independent |
| node_id | str | O | Nodo eléctrico del puesto (para la traza) |

### Unidad de transformador (`transformer_units`) — placa propia (§5.2)
| Campo | Tipo | R/O | Descripción |
|---|---|---|---|
| unit_id | str | R | Id de la unidad |
| site_id | str | R | Puesto al que pertenece |
| sn_kva | float | R | Potencia nominal |
| p0_kw | float | R | Pérdidas de vacío (placa o catálogo) |
| pk_kw | float | R | Pérdidas de carga nominal |
| voltage_ln | float | O | Tensión nominal (para regla P04) |
| phase | enum | O | Fase(s) que sirve |

### Tramo (`segments`) — vano/conductor (geometría de línea)
| Campo | Tipo | R/O | Descripción |
|---|---|---|---|
| segment_id | str | R | Id del tramo |
| node_from, node_to | str | R | Nodos extremos (definen la conectividad) |
| conductor_code | str | R | Código de conductor (catálogo de impedancias) |
| r_ohm_per_km, x_ohm_per_km | float | R | Impedancia por km |
| ampacity_a | float | R | Ampacidad |
| phase | enum | R | Fases del tramo |
| voltage_ll | float | R | Tensión nominal línea-línea |
| section | str | O | primary / secondary |
| length_m | float | O | Longitud (se deriva de la geometría si falta) |

### Cliente (`customers`) — unidad de servicio (medidor) (§5.3)
| Campo | Tipo | R/O | Descripción |
|---|---|---|---|
| customer_unit_id | str | R | Id de la unidad de servicio |
| site_id | str | R | Puesto de cliente (comparten acometida) |
| pole_id | str | O | Poste de la acometida |
| tariff_class | enum | R | residential / commercial / industrial / streetlight_* |
| installed_load_kw | float | O | Carga instalada |
| service_drop_kva | float | O | Capacidad de la acometida |
| transformer_site_id | str | O | Puesto de transformación (mejor por traza, no declarado) |

### Luminaria (`streetlights`), Dispositivo (`switching_devices`)
Ver `lossan schema inspect`. Claves: `streetlight_id/technology/lamp_w` y
`device_id/node_id/type/normal_state (NA|NC)`.

### Consumo (`consumption`) y Cabecera (`header_meters`) — sistema comercial
| Entidad | Campos | Nota |
|---|---|---|
| consumption | customer_unit_id, feeder_id, year_month, kwh, [kvarh, estimated] | Cárgalo con `lossan ingest-consumption` |
| header_meters | feeder_id, year_month, kwh, [kvarh] | Cárgalo con `lossan ingest-header` |

> `kvarh` es **muy recomendable**: permite cosφ real por cliente (método
> preferente §9.2). `estimated=true` marca lecturas estimadas (no se imputan en
> silencio, §13).

### Inspección de campo (`field_inspections`) — retorno de campaña (§23.1)
`inspection_id, site_id, [customer_unit_id], inspected_date, finding(bool),
finding_type, recovered_kwh, actual_cost_usd, source(directed|exploration)`.
Sin este retorno el modelo **no mejora**: defínelo desde el inicio.

---

## 2. Cómo se analizan los elementos conectados por alimentador (ya implementado)

El análisis de conectividad **ya está hecho** (módulo `topology`, fase F2) y es
la base de todo el cálculo de pérdidas. El flujo:

1. **Construcción del grafo** (`FeederGraph.build`): con los `segments`
   (`node_from → node_to`) se arma un grafo dirigido desde la fuente
   (`<feeder>-SRC`) hacia las cargas, usando **rustworkx**. La unidad de
   transformación se agrega como arista primario→secundario. Es **independiente
   de arcpy**: no usa la red geométrica de ArcGIS.
2. **Trazas**: `trace_downstream`, `trace_upstream`, `path_to_source`
   (distancia e impedancia acumuladas), `subtree_load` (clientes, kVA,
   luminarias aguas abajo) y `branch_decomposition`.
3. **Asignación por traza, no por campo declarado**: cada cliente y luminaria se
   asigna al puesto que resulta de la traza; las discrepancias con el campo
   declarado se marcan como hallazgo (R15).
4. **Zonas de protección**: los dispositivos segmentan el árbol en zonas
   (ramal operativo), la unidad accionable para balance y campaña (§7.5).
5. **Validaciones**: radialidad, islas, multi-alimentación, `feeder_id`
   declarado vs. traza (R08), fases y tensión (R06/R07).

Puedes verlo por alimentador con:
```bash
lossan feeder-report F0000
```
que imprime nodos/tramos, clientes y puestos conectados por traza, la validación
topológica y el **desglose de pérdidas** (cabecera → facturada → AP → técnicas →
PNT), es decir, exactamente “lo necesario del proyecto: las pérdidas”.

---

## 3. De la conectividad a las pérdidas

```
elementos conectados por traza  →  carga aguas abajo por puesto/zona (subtree_load)
        →  flujo de potencia (I²R por tramo + P0/Pk por unidad)  =  Pérdidas técnicas
E_cabecera − E_facturada − E_AP − ENS − Pérdidas_técnicas        =  PNT (no técnicas)
```

La conectividad determina **qué carga cuelga de qué elemento**; sin ella el
balance no cierra y la PNT es espuria. Por eso F2 es prerrequisito de F5 (balance)
y F6 (estimación de estado que localiza la carga no contabilizada por zona).

Ver **[HISTORIA.md](HISTORIA.md)** para cuánto histórico de consumo se necesita.
