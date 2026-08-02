"""Adaptadores de entrada/salida (§2.5).

El núcleo analítico NO depende de arcpy. La lectura/escritura de File
Geodatabase se hace con GDAL/OpenFileGDB vía pyogrio, disponible en cualquier
sistema operativo. arcpy quedaría solo como adaptador alternativo si se desea.
"""
from .fgdb import ingest_fgdb, list_layers, read_layer
from .export import export_sample, export_results, build_geodataframes

__all__ = [
    "ingest_fgdb", "list_layers", "read_layer",
    "export_sample", "export_results", "build_geodataframes",
]
