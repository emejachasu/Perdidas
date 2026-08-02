# Guía de calibración del modelo (Anexo A)

Todos los parámetros viven en `config/*.yaml` (nunca en el código). Aquí se
explica qué toca cada uno, cómo afecta el resultado y cómo calibrarlo contra
tus datos (medidor de cabecera e inspecciones). Reejecuta `lossan run --force`
tras cambiar la configuración.

---

## 1. Factor de pérdidas — `config/electrical.yaml: loss_factor_k`
`FP = k·FC + (1−k)·FC²` (Buller–Woodrow). Afecta la **energía perdida** en
conductores y transformadores.
- **Default:** 0.15.
- **Calibración:** ajusta `k` por mínimos cuadrados contra la curva del medidor
  de cabecera (compara `FC` real vs `FP` que reproduce las pérdidas medidas).
  Un `k` mayor sube las pérdidas técnicas y, por diferencia, baja la PNT.
- **Verificación automática:** el sistema garantiza `FC² ≤ FP ≤ FC`.

## 2. Factor de potencia por clase — `power_factor_by_class`
Convierte energía a potencia reactiva cuando no hay kVArh. Afecta S, I y
pérdidas.
- **Calibración:** compara el cosφ implícito de la mezcla de clases del
  alimentador contra el cosφ medido en cabecera y corrige por clase.
- Si tienes **kVArh por cliente**, el sistema lo usa directamente (preferente) y
  este parámetro deja de influir.

## 3. Velander y coincidencia — `velander`, `coincidence`
`D_max = a·E + b·√E` y `FCoinc(n) = A + B/√n`. Afectan la **demanda
diversificada** por puesto y, por tanto, la cargabilidad.
- **Calibración:** ajusta `a,b` y `A,B` con puestos que sí tengan medición de
  demanda; valida que la demanda estimada reproduzca los picos observados.

## 4. Temperatura de operación — `temperature`
Corrige `R` del conductor. Afecta pérdidas (`R` sube ~12 % de 20 °C a 50 °C).
- **Default:** aéreo 50 °C, subterráneo 65 °C. Ajusta a tu clima/carga.

## 5. Umbrales de cargabilidad — `config/thresholds.yaml: loadability`
Definen las clases sobrecargado/adecuado/subutilizado (`S_max/S_capacidad`).
- Ajusta según la política de la empresa (p. ej. bajar `overloaded` a 0.9 para
  ser más conservador con reemplazos).

## 6. Configuración de banco — reglas §5.2 (automático)
La capacidad se calcula por configuración de banco (delta abierto = √3·S, etc.).
- Si tu FGDB trae el **atributo de banco/conexión**, mapéalo a `bank_config`.
- Si no, el sistema lo infiere por conectividad del secundario (marcado como
  dato derivado con nivel de confianza).

## 7. Alumbrado público — `config/streetlight.yaml`
`hours_on_default` y pérdidas/cosφ por tecnología.
- **Recomendado:** habilita el cálculo por efemérides (latitud/mes) cuando esté
  disponible, en vez del valor fijo de 11,5 h.

## 8. Minería de etiquetas — `config/thresholds.yaml: label_mining`
Umbrales de los mecanismos M1–M8 (caída %, meses, salto %, ceros...).
- **Calibración clave (§22.8):** ejecuta y revisa el **recall contra los hurtos
  confirmados** (lo reporta `mine_labels`/`validate_against_confirmed`). Sube
  los umbrales si hay demasiados falsos positivos; bájalos si el recall es bajo.

## 9. Método de PU learning — (parámetro de `train_risk_model`)
`elkan_noto` (default) | `bagging_pu` | `spies`. Cambian cómo se corrige el
sesgo de etiquetas.
- **Cómo elegir:** compara **Precision@k** entre métodos con tus datos y quédate
  con el mejor en la cabeza del ranking (el top 2–7 % es lo único que importa).

## 10. Explicabilidad — `config/thresholds.yaml: explain.top_n`
Cuántos casos de la cabeza del ranking reciben razones SHAP. Súbelo si tu
campaña es grande; bájalo para acelerar corridas.

## 11. Presupuesto y economía — `config/budget.yaml`
`field_usd`, `exploration_reserve_frac`, `tariff_usd_per_kwh`,
`recovery_months`, `cost_per_visit_usd` por tipo de puesto, cuadrillas.
- **Consecuencia directa (§17.2):** el número de visitas financiables =
  `field_usd / costo_por_visita` fija el `k` de Precision@k. **Mide el costo
  real por visita en la primera campaña y realiméntalo aquí.**
- La reserva de exploración (5–10 %) es obligatoria para no degradar el modelo.

---

## Flujo de calibración recomendado

1. **Informe de reconciliación (F3):** corre y revisa que P y Q corregidos
   cuadren con la cabecera; ajusta §1–§4.
2. **Balance por alimentador:** apunta a residuo < 0,5 %; si no cierra, revisa
   AP (§7), transferencias entre alimentadores y lecturas estimadas.
3. **Minería de etiquetas:** valida recall contra confirmados; ajusta §8.
4. **Riesgo:** compara métodos PU por Precision@k; calibra §9.
5. **Campaña:** fija presupuesto/costos reales; revisa la curva de asignación.

Cada corrida registra los parámetros usados (reproducibilidad, §22.12).
