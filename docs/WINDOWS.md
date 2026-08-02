# Guía de implementación en Windows — paso a paso

Esta guía instala y ejecuta la plataforma en Windows, genera datos de prueba,
conecta tu **File Geodatabase (FGDB)** real y publica resultados a GIS. El
núcleo **no depende de `arcpy`** (lee/escribe FGDB con GDAL/OpenFileGDB), así
que funciona con o sin ArcGIS Pro instalado.

---

## 1. Prerrequisitos

1. **Python 3.11 (64-bit)** — https://www.python.org/downloads/windows/
   Durante la instalación marca **"Add python.exe to PATH"**.
2. **Git para Windows** (opcional, para clonar) — https://git-scm.com/download/win
3. (Opcional) **ArcGIS Pro** si quieres abrir los resultados en ArcGIS. No es
   necesario para ejecutar la plataforma.

Verifica en *PowerShell*:
```powershell
python --version      # Python 3.11.x
```

> **Alternativa con Conda/ArcGIS:** si usas el Python de ArcGIS Pro, puedes
> crear un entorno clonado (`conda create --clone arcgispro-py3 -n lossan`) y
> saltar al paso 3. GDAL ya viene incluido.

---

## 2. Obtener el proyecto

```powershell
cd %USERPROFILE%\Documents
git clone <URL-del-repo> Perdidas
cd Perdidas
```
(o descarga el ZIP del repositorio y descomprímelo).

---

## 3. Entorno virtual e instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # si PowerShell bloquea scripts, ver Nota A
python -m pip install --upgrade pip
pip install -e ".[dashboard,dev,power,ml,geo]"
```

- `dashboard` = Streamlit + Plotly · `dev` = pytest · `power` = OpenDSS ·
  `ml` = LightGBM/SHAP/pyod · `geo` = geopandas/pyogrio (lectura FGDB).

Comprueba la instalación:
```powershell
pytest -q
lossan --help
```

> **Nota A (ejecución de scripts en PowerShell):** si `Activate.ps1` da error,
> ejecuta una vez:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
> o usa `.\.venv\Scripts\activate.bat` desde CMD.

---

## 4. Probar con datos sintéticos (sin tu FGDB todavía)

```powershell
# 1) generar el universo sintético (perfil 'demo' = 12 alimentadores)
lossan generate

# 2) ejecutar todo el pipeline (topología, balance, flujo, riesgo, plan)
lossan run

# 3) ver el avance por alimentador
lossan status

# 4) abrir el dashboard web
lossan dashboard
```
Abre el navegador en **http://localhost:8501**.

Para cambiar la escala edita `config\scale.yaml` (`active_profile: demo | full`)
o usa `lossan generate --profile full` (universo objetivo de 960 alimentadores).

---

## 5. Conectar TU File Geodatabase real

### 5.1 Ver las capas de tu FGDB
```powershell
lossan fgdb-layers "C:\ruta\a\tu_red.gdb"
```

### 5.2 Ajustar el mapeo de esquema
Abre `config\schema_mapping.yaml` y para cada entidad canónica pon el **nombre
de tu feature class** y el **nombre de tus campos**. Ejemplo real:
```yaml
layers:
  poles:
    layer: Estructura_Soporte        # tu feature class de postes
    fields:
      pole_id: OBJECTID
      pole_type: TIPO_ESTRUCTURA
      height_m: ALTURA
  segments:
    layer: Conductor_Primario
    fields:
      segment_id: OBJECTID
      conductor_code: TIPO_CONDUCTOR
      phase: FASES
      voltage_ll: TENSION
  transformer_units:
    layer: Transformador
    fields:
      unit_id: OBJECTID
      site_id: ID_PUESTO
      sn_kva: KVA
      p0_kw: PERDIDAS_VACIO
      pk_kw: PERDIDAS_CARGA
```
Lo que no exista se omite con una advertencia (no falla). `x/y` de los postes y
`length_m` de los tramos se derivan de la geometría automáticamente.

### 5.3 Ingerir a BRONZE
```powershell
lossan ingest-fgdb "C:\ruta\a\tu_red.gdb" --extract-date 2026-08-02
```

### 5.4 Cargar el consumo histórico (del sistema comercial)
El consumo y la cabecera suelen venir en CSV/tabla, no en la FGDB. Deja tus
archivos con estas columnas y colócalos en BRONZE:
- `consumption`: `customer_unit_id, feeder_id, year_month, kwh, kvarh, estimated`
- `header_meters`: `feeder_id, year_month, kwh, kvarh`

(Contacta si tu formato difiere; el adaptador de consumo se ajusta en `io/`.)

### 5.5 Ejecutar y publicar
```powershell
lossan run
lossan export-results --out "C:\salida\resultados" --fmt fgdb
lossan dashboard
```
`export-results` genera capas GIS listas para ArcGIS: `CustomerUnits_Risk`,
`TransformerSites_Balance`, `Segments_Anomalies`, `Inspection_Plan`.

---

## 6. Calibrar el modelo a tu red

Ver **[docs/TUNING.md](TUNING.md)**: qué parámetro tocar en `config\*.yaml`
para ajustar factor de pérdidas, cosφ, umbrales de cargabilidad, mecanismos de
minería de etiquetas, método de PU learning y el presupuesto de campaña.

---

## 7. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `Activate.ps1` bloqueado | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (Nota A) |
| `Layer '...' could not be opened` | El nombre en `schema_mapping.yaml` no coincide con `fgdb-layers` |
| FGDB no abre | Necesita GDAL ≥ 3.6 (viene con `pip install pyogrio`); revisa `pip show pyogrio` |
| El dashboard no abre | Revisa que `lossan run` haya generado GOLD (`lossan status`) |
| Rendimiento lento con universo grande | Usa `lossan run` incremental (solo reprocesa lo que cambió por hash) |
| `pip install` falla al compilar | Usa el Python de ArcGIS (Conda) o instala *Microsoft C++ Build Tools* |

---

## 8. Flujo completo resumido

```powershell
.\.venv\Scripts\Activate.ps1
lossan fgdb-layers "C:\...\red.gdb"        # inspeccionar
# editar config\schema_mapping.yaml
lossan ingest-fgdb "C:\...\red.gdb"        # BRONZE
# cargar consumption/header_meters (CSV -> BRONZE)
lossan run                                  # análisis completo
lossan export-results --fmt fgdb            # capas GIS
lossan dashboard                            # tablero
```
