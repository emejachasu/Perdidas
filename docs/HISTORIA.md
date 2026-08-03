# ¿Cuánto histórico de consumo se necesita?

El parámetro es `config/scale.yaml: history_months` (por defecto **48**). El
requerimiento pide **36–60 meses**. Aquí el porqué, con el mínimo y el
recomendado por tipo de análisis.

## Resumen ejecutivo

| Escenario | Meses | Qué habilita | Qué se pierde por debajo |
|---|---|---|---|
| **Mínimo viable** | **12** | Balance de energía, estacionalidad de un ciclo, cargabilidad | No hay comparación interanual ni patrón de hurto robusto |
| **Recomendado** | **36** | Detección de hurto fiable, validación temporal del ML, tendencia vs. estacionalidad | — |
| **Óptimo (spec)** | **48–60** | Backtesting multi-año, calibración estable, cambios lentos | — |

**Recomendación:** empieza con lo que tengas (mínimo 12–24 m para resultados
útiles), apunta a **36** para el modelo de hurto, y conserva hasta **60**.

## Requisito por análisis

| Análisis | Mínimo | Recomendado | Razón |
|---|---|---|---|
| Balance de energía / PNT | 1–3 m | 12 m | El balance cierra mes a mes; 12 m promedia ruido |
| Estacionalidad (curvas de carga) | 12 m | 24 m | Un ciclo anual completo; 24 m separa estación de tendencia |
| Factor de carga / pérdidas (calibrar `k`) | 12 m | 24 m | Ajuste contra la curva de cabecera de al menos un año |
| cosφ real (kVArh) | 3 m | 12 m | Estabilidad del factor de potencia |
| **M1 caída y recuperación** | 12 m | 18–24 m | Necesita nivel base + caída sostenida + recuperación |
| **M2 salto tras intervención** | 12 m | 24 m | Comparar media pre/post de forma estable |
| **M5 ruptura de nivel** (change point) | 9 m | 18 m | Segmentos suficientes a cada lado del cambio |
| **M6 colapso de factor de potencia** | 6 m | 12 m | Requiere kVArh histórico |
| Ratios interanuales (YoY) | 24 m | 36 m | Comparar el mismo mes de años distintos |
| **Validación temporal del ML** (TimeSeriesSplit, backtesting T→T+1) | 24 m | 36 m | Ventana de entrenamiento + ventana de evaluación sin fuga |
| Corrección de sesgo / propensidad PU | 24 m | 36 m+ | Cuantos más meses y más inspecciones, mejor `c` |

## Notas prácticas

- **Regla anti-fuga (§15.3):** las features usan sólo datos hasta la fecha de
  corte. Con `build_features(consumption, customers, cutoff="2023-12")` puedes
  entrenar hasta T y evaluar en T+1 (backtesting). Necesitas historia a ambos
  lados del corte.
- **Lecturas estimadas:** márcalas (`estimated=true`); si una fracción alta del
  histórico es estimada, sube el mínimo de meses para compensar el ruido.
- **Resolución:** el modelo trabaja con **consumo mensual**. Si dispones de
  **curvas horarias de cabecera**, calibran mejor FC/FP/cosφ (Anexo B) aunque no
  cambian el requisito de meses.
- **Cambia el parámetro, no el código:** ajusta `history_months` en
  `config/scale.yaml`; el pipeline y el generador sintético lo respetan.

## Conclusión

Para **detectar pérdidas no técnicas con confianza**, el punto dulce es
**36 meses**: cubre dos ciclos estacionales, habilita comparación interanual y
da ventana de validación temporal al modelo. Menos de 24 meses degrada la
detección de hurto (no la del balance ni la de pérdidas técnicas, que funcionan
con pocos meses).
