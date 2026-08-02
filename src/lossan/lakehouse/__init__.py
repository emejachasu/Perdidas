"""Lakehouse de tres capas Bronze/Silver/Gold sobre Parquet + DuckDB (§2.2)."""
from .storage import Lakehouse, feeder_input_hash

__all__ = ["Lakehouse", "feeder_input_hash"]
