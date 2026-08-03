# Ajuste al modelo de datos de CNEL EP (SIGELEC / ArcFM)

Adaptación del modelo eléctrico a la estructura real de la geodatabase de CNEL,
a partir del diccionario de datos y de las *relationship classes* entregados.

## 1. La jerarquía real

```
ESTRUCTURA (soporte físico)
  EstructuraSoporte | EstructuraANivel | EstructuraSubterranea
        │
        ├── PUESTO (agrupación funcional)  ──  UNIDAD (equipo con placa)
        │     PuestoTransfDistribucion     ──  UNIDADTRANSFDISTRIBUCION   (1:N)
        │     PuestoSeccionadorFusible     ──  UNIDADFUSIBLE              (1:N)
        │     PuestoProteccionDinamico     ──  UNIDADPROTECCIONDINAMICO   (1:N)
        │     PuestoReguladorTension       ──  UNIDADREGULADORTENSION     (1:N)
        │     PuestoCorrectorFactorPotencia──  UNIDADCAPACITOR            (1:N)
        │     PuestoProteccionBajaTension  ──  UNIDADPROTECCIONBAJATENSION(1:N)
        │
        └── PUNTO DE CARGA                 ──  CONEXIÓN CONSUMIDOR
              PuntoCarga                   ──  CONEXIONCONSUMIDOR         (1:N)
                    ↑ el edificio                    ↑ los medidores
```

**El caso del edificio**: un `PuntoCarga` es la acometida física (un predio, un
edificio) y puede tener **varias** `CONEXIONCONSUMIDOR` (medidores). Es el mismo
patrón puesto→unidad que en el resto de la red.

Las relaciones se resuelven por **`GLOBALID`** (PK del padre) contra
`<PADRE>GLOBALID` (FK del hijo) — nunca por geometría ni por nombres. La
conectividad de red usa el par `CIRCUITSOURCEGUID` / `PARENTCIRCUITSOURCEGUID`
de ArcFM, que ya resuelve la traza padre→hijo.

## 2. Correspondencia con el modelo canónico

| CNEL | Canónico | Nota |
|---|---|---|
| `EstructuraSoporte` / `ANivel` / `Subterranea` | `poles` | soporte físico; unidad de visita |
| `PuestoTransfDistribucion` | `sites` (kind=transformer) | capacidad **por configuración de banco** |
| `UNIDADTRANSFDISTRIBUCION` | `transformer_units` | placa por unidad; P0/Pk del catálogo |
| **`PuntoCarga`** | **`load_points`** | acometida compartida (el edificio) |
| **`CONEXIONCONSUMIDOR`** | **`customers`** | unidad de servicio = medidor |
| `Luminaria` + `UNIDADLUMINARIA` | `streetlights` | |
| `PuestoProteccionDinamico` | `switching_devices` | define zonas de protección |

## 2.1 Identificadores únicos

| Identificador | Dónde vive | Uso |
|---|---|---|
| **`CODIGOUNICO`** | `CONEXIONCONSUMIDOR` y `ATRIBUTOSCONSUMIDOR` | **id canónico de la conexión** (`customer_unit_id`) y clave de unión entre la capa gráfica y los atributos comerciales |
| **`CUENTACONTRATO`** | `ATRIBUTOSCONSUMIDOR` | **id único del sistema comercial**: por él llega el histórico de consumo |
| `GLOBALID` | todas las capas | trazabilidad SIG y resolución de las relaciones padre-hijo |

El `GLOBALID` **no** se usa como identificador de negocio de la conexión: se
conserva en `global_id` y sirve de respaldo si `CODIGOUNICO` viniera vacío (en
ese caso el adaptador avisa, para que la conexión no desaparezca del balance).

`ATRIBUTOSCONSUMIDOR` aporta además lo que la capa gráfica no tiene:
**`TIPOTARIFA`** (→ clase tarifaria), `POTENCIAACTIVA` (carga instalada),
`CDAFAS`, estado del servicio y datos del medidor.

## 3. Qué cambió en el modelo eléctrico

### 3.1 Configuración de banco: ya no se infiere
`PuestoTransfDistribucion.CONFIGURACIONLADOBAJA` (dominio *Config Lado Baja
Banco Transf*) **trae la configuración explícita**. Se mapea directamente a
`BankConfig`, eliminando la inferencia por conectividad del secundario. Si el
valor no está en el dominio, se deduce por el número de unidades y se marca
como derivado — no se inventa.

Ejemplo verificado: un puesto con `CONFIGURACIONLADOBAJA = "Delta Abierta"` y
2 unidades de 37,5 kVA rinde **√3 × 37,5 = 64,95 kVA**, no 75 kVA.

### 3.2 Fase real por unidad y por conexión
`FASECONEXION` (dominio *Phase Designation*, bitmask C=1, B=2, A=4) está en el
puesto, en cada unidad y en el punto de carga; `SECUENCIAFASE` en la conexión
consumidor. Esto habilita el desbalance real y la corriente de neutro (§14.2)
sin estimaciones.

> Los valores de dominio no venían en el diccionario. Están en
> `config/cnel_mapping.yaml` con el estándar ArcFM y **deben verificarse**
> contra la GDB real: `lossan cnel-domains <ruta.gdb>`.

### 3.3 Coincidencia en dos niveles (el cambio de fondo)
Antes la demanda del puesto se estimaba desde la energía agregada. Ahora:

1. **Dentro del punto de carga**: se aplica el factor de coincidencia entre las
   conexiones del mismo edificio (comparten acometida y ya están diversificadas
   entre sí).
2. **Entre puntos de carga**: se aplica de nuevo al agregar al transformador.

Sumar los picos de cada medidor uno a uno sobrestima la demanda —es el error 3
de §9.1. Medido en el universo de prueba: **35,5 % de sobrestimación** evitada
en los puntos multi-medidor.

### 3.4 Coherencia de acometida y dispersión intra-punto
- La capacidad de acometida es **del punto de carga**, y se contrasta contra la
  demanda agregada de sus conexiones → hallazgos `acometida_sobrecargada` /
  `acometida_subutilizada`.
- Una conexión muy por debajo de sus pares **del mismo punto**, con la misma
  acometida, es señal fuerte de derivación en el tablero o riser común →
  hallazgo `dispersion_intra_punto`, que alimenta el mecanismo **M8** (§15.2).

### 3.5 Costo de campo por punto de carga
Una visita cubre el punto de carga completo (todas sus conexiones). El costo es
por punto y el beneficio la suma sobre sus medidores — la asimetría de §17.1 que
cambia qué se selecciona, no solo el orden.

## 4. Uso

```bash
# 1) verificar los dominios reales de tu GDB y ajustar el mapeo si difieren
lossan cnel-domains "C:\ruta\SIGELEC.gdb" --domain "Phase"

# 2) ingerir resolviendo la jerarquía completa
lossan ingest-cnel "C:\ruta\SIGELEC.gdb"

# 3) consumo del sistema comercial: llega por CUENTACONTRATO y se traduce
#    automáticamente a CODIGOUNICO usando ATRIBUTOSCONSUMIDOR
lossan ingest-consumption consumo.csv --map cuenta_contrato=CUENTA_CONTRATO,year_month=PERIODO,kwh=CONSUMO

# 4) analizar
lossan run
```

La ingesta reporta la jerarquía detectada (cuántas unidades por puesto y cuántas
conexiones por punto de carga), que es la verificación de que el modelo se leyó
correctamente. La ingesta de consumo reporta la **tasa de cruce** comercial↔SIG
y avisa por debajo del 95 %: un cruce bajo invalida el balance, así que es el
primer control de calidad a mirar.

## 4.1 Zonas de protección desde el trazado nativo

ArcFM ya resuelve la traza: `PuestoProteccionDinamico.CIRCUITSOURCEGUID` se
propaga a `PARENTCIRCUITSOURCEGUID` de todo lo que cuelga aguas abajo. La
función `build_zones_from_arcfm()` obtiene las zonas agrupando por esa clave,
sin recorrer el grafo, y coincide con la definición operativa de ramal (§7.5).
Se usa como fuente primaria cuando el dato existe, y el recorrido del grafo
(`build_protection_zones`) queda como respaldo y contraste.

## 5. Datos que la GDB no tiene

| Falta | Consecuencia | Mitigación |
|---|---|---|
| `P0` / `Pk` por unidad | pérdidas de transformador estimadas | catálogo por kVA; `plate_source='catalog'` (Anexo B.4) |
| Clase tarifaria en la conexión | grupos par menos precisos | se completa desde el sistema comercial vía `CODIGOCLIENTE` |
| Capacidad de acometida | no se puede validar coherencia | se estima desde la carga instalada |

Ver [DATOS_REQUERIDOS.md](DATOS_REQUERIDOS.md) para el inventario completo.
