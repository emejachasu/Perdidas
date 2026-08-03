# Revisión completa del proyecto — hallazgos y correcciones

Auditoría de correctitud sobre todo el código (163 funciones, 83 tests).
Se hallaron **7 defectos**, todos corregidos y blindados con tests de regresión
en `tests/test_regressions.py`.

---

## 🔴 1. La métrica de cierre del balance era una identidad algebraica

**Severidad: crítica.** Era el defecto más grave: una métrica que aparentaba
validar el criterio de aceptación §22.3 sin validar nada.

```python
pnt          = losses_total - energy_technical            # definición de PNT
residual_pct = (losses_total - energy_technical - pnt)    # ≡ 0  SIEMPRE
```

Al sustituir `pnt`, el numerador se anula por construcción: `x − x = 0`. En
consecuencia `balance_closed = abs(residual_pct) < 0.5` era **siempre `True`**,
incluso con una PNT de −95 %. Los "12/12 balances cerrados · residuo 0,000 %"
que se venían reportando no significaban nada.

**Causa raíz:** la PNT se *define* por diferencia (identidad contable), así que
recomputar esa misma resta nunca puede verificarla.

**Corrección** (`pipeline/balance.py`): el cierre ahora se verifica con
**coherencia física independiente**, y se añade una comparación contra una
estimación por otro camino:

| Verificación | Qué comprueba |
|---|---|
| `pnt_non_negative` | PNT ≥ 0 (§13: PNT<0 es error inequívoco) |
| `accounted_within_header` | facturada + AP + ENS ≤ cabecera |
| `total_losses_plausible` | pérdidas totales dentro del rango configurado |
| `technical_plausible` | pérdidas técnicas en rango plausible |
| `header_positive` | energía de cabecera > 0 |

- `balance_coherent` + `failed_checks` sustituyen a `residual_pct`.
- `unexplained_pct`: discrepancia contra la PNT que estima el **WLS del DSSE**
  (camino distinto, ponderado por incertidumbre) → 0,10–0,14 % en la demo.

**Verificado:** con la cabecera a la mitad fallan 3 verificaciones; con la
cabecera duplicada falla `total_losses_plausible`. Ya **detecta** incoherencias.

---

## 🟠 2. El alumbrado público se repartía uniformemente entre todos los puestos

**Severidad: alta.** `energy_streetlight / len(sites)` daba a cada puesto la
misma porción de AP, **ignorando `streetlights.transformer_site_id`** (la traza
real). §10.2 advierte justo lo contrario: el AP debe ir al puesto que lo
alimenta, porque es carga nocturna que decide la clasificación de cargabilidad.

**Corrección:** el AP se calcula por luminaria y se acumula en **su** puesto por
traza. Test de regresión: mover las luminarias entre dos puestos cambia la
cargabilidad de ambos (antes era idéntica).

---

## 🟠 3. `subtree_load` identificaba clientes por el nombre del nodo

**Severidad: alta (rompe con datos reales).** Contaba clientes con
`"-C" in nodo` y luminarias con `"-L" in nodo`. Funciona solo con los ids
sintéticos; con los del SIG real produce falsos positivos y negativos
(`TRAFO-CS-9` contaba como cliente; `MEDIDOR-A` no se contaba). El parámetro
`leaf_prefixes` ni siquiera se usaba.

**Corrección:** conjuntos explícitos de ids (`register_leaf_nodes`), poblados
automáticamente por `FeederGraph.build(...)`. Sin registro devuelve 0 en vez de
adivinar.

---

## 🟡 4. Parámetros de negocio escritos en el código (viola §22.13)

`fc = 0.45` (factor de carga), `SECONDARY_LOSS_PCT = 0.035`, `/ 0.92` (factor de
potencia) y `730.0` estaban embebidos en `balance.py`, `imbalance.py`,
`analyze.py` y `reconciliation.py` — justo lo que el criterio 13 prohíbe, y son
parámetros de calibración del Anexo A.

**Corrección:** movidos a `config/electrical.yaml` (`default_load_factor`,
`default_site_pf`, `secondary_loss_frac`, `hours_per_month`). Un test de
regresión falla si vuelven a aparecer en el código.

---

## 🟡 5. El generador nunca producía puestos de cliente multi-unidad

`site_id = f"...CS{i // 1:06d}"` — `i // 1` es `i`, así que cada cliente tenía su
propio puesto. Consecuencia silenciosa: el **mecanismo M8** (dispersión
intra-puesto, §5.3) **nunca podía dispararse** y la asimetría de costo por visita
de §17.1 no se ejercitaba a nivel de puesto de cliente.

**Corrección:** distribución realista (1–6 unidades por puesto); las unidades de
un mismo puesto comparten poste, transformador y fase (misma acometida).
**Resultado:** M8 ahora produce etiquetas (15 en el alimentador de prueba).

---

## 🟡 6. Trabajo duplicado en cada alimentador

`_customer_risk` (pivote completo del histórico) se calculaba en el balance y
después se **sobrescribía** con el modelo ML en modo `full`.

**Corrección:** `analyze_feeder(..., with_risk_proxy=...)`; solo se calcula
cuando el ML no va a reemplazarlo (modo `n1`).

---

## 🟢 7. Regla R09 con complejidad innecesaria

Llamaba `subtree_load` por **cada** tramo → O(V·(V+E)). Medido: ~0,1 s por
alimentador y ~1 min para 960 — tolerable gracias a la partición, pero evitable.

**Corrección:** `accumulate_downstream()` acumula la carga de todo el árbol en
**una pasada O(V+E)**. Además se corrigió una inconsistencia de unidades: el
`load_map` está en kW y se usaba como si fuera kVA; ahora se convierte con el
factor de potencia.

---

## Efectos colaterales corregidos

Los cambios de esquema rompieron tres consumidores, detectados y arreglados:
- `lossan feeder-report` lanzaba `KeyError: 'residual_pct'`.
- El dashboard mostraba la misma columna eliminada.
- `reliability_index` recibía el residuo nulo como penalización (siempre 0);
  ahora recibe la incoherencia real del balance.

## Estado tras la revisión

- **83 tests en verde** (6 nuevos de regresión).
- **100 % de docstrings** (163/163).
- Dashboard, reportes PDF y CLI verificados sin errores.

## Lección transversal

El defecto crítico y el del generador comparten un patrón: **verificaciones que
no verifican**. Una métrica derivada de la propia definición que pretende
validarla, y un dato sintético que nunca ejercita la ruta que dice cubrir. Los
tests de `test_regressions.py` fijan ambos comprobando que el sistema **detecta
el fallo cuando se le inyecta**, no solo que "pasa" en el caso feliz.
