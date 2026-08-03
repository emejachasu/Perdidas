"""Adaptadores de entrada/salida (§2.5).

El núcleo analítico NO depende de arcpy. La lectura/escritura de File
Geodatabase se hace con GDAL/OpenFileGDB vía pyogrio, disponible en cualquier
sistema operativo. arcpy quedaría solo como adaptador alternativo si se desea.
"""
from .fgdb import ingest_fgdb, list_layers, read_layer
from .export import export_sample, export_results, build_geodataframes
from .consumption import ingest_consumption, ingest_header
from .templates import build_templates, TEMPLATES
from .cnel import (build_canonical, ingest_cnel_fgdb, load_cnel_mapping,
                   site_unit_summary, decode_phase, decode_bank_config)

__all__ = [
    "ingest_fgdb", "list_layers", "read_layer",
    "export_sample", "export_results", "build_geodataframes",
    "ingest_consumption", "ingest_header",
    "build_templates", "TEMPLATES",
    "build_canonical", "ingest_cnel_fgdb", "load_cnel_mapping",
    "site_unit_summary", "decode_phase", "decode_bank_config",
]
