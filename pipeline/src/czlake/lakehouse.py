"""Iceberg tables in a local PyIceberg SQL catalog, read back through DuckDB.

Layers are Iceberg namespaces: raw_idx (inventory of raw landings), staging, core, marts.
"""
from __future__ import annotations

import datetime as dt
import warnings

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
from pyiceberg.catalog.sql import SqlCatalog

from .paths import CATALOG_DB, DUCKDB_FILE, WAREHOUSE

warnings.filterwarnings("ignore", message=".*Delete operation did not match any records.*")

LAYERS = ("raw_idx", "staging", "core", "marts")
_CAT = None


def catalog() -> SqlCatalog:
    global _CAT
    if _CAT is None:
        _CAT = SqlCatalog("czlake", uri=f"sqlite:///{CATALOG_DB}", warehouse=f"file://{WAREHOUSE}")
        for ns in LAYERS:
            _CAT.create_namespace_if_not_exists(ns)
    return _CAT


def _iceberg_safe(t: pa.Table) -> pa.Table:
    """Cast Arrow types Iceberg cannot store (null, unsigned, large types, naive dicts)."""
    if isinstance(t, pa.RecordBatchReader):
        t = t.read_all()
    cols, fields = [], []
    for f, col in zip(t.schema, t.columns):
        typ = f.type
        if pa.types.is_null(typ):
            col, typ = col.cast(pa.string()), pa.string()
        elif pa.types.is_unsigned_integer(typ):
            col, typ = col.cast(pa.int64()), pa.int64()
        elif pa.types.is_large_string(typ):
            col, typ = col.cast(pa.string()), pa.string()
        elif pa.types.is_decimal(typ):
            col, typ = col.cast(pa.float64()), pa.float64()
        elif pa.types.is_dictionary(typ):
            col, typ = col.cast(typ.value_type), typ.value_type
        elif pa.types.is_timestamp(typ) and typ.tz is None and typ.unit == "ns":
            col, typ = col.cast(pa.timestamp("us")), pa.timestamp("us")
        elif pa.types.is_timestamp(typ) and typ.unit == "ns":
            col, typ = col.cast(pa.timestamp("us", tz=typ.tz)), pa.timestamp("us", tz=typ.tz)
        cols.append(col)
        fields.append(pa.field(f.name, typ, nullable=True))
    return pa.Table.from_arrays(cols, schema=pa.schema(fields))


def write(layer: str, name: str, table: pa.Table, mode: str = "overwrite"):
    """Write an Arrow table to <layer>.<name>; evolves the schema by column name."""
    assert layer in LAYERS, layer
    cat = catalog()
    table = _iceberg_safe(table)
    ident = f"{layer}.{name}"
    if cat.table_exists(ident):
        t = cat.load_table(ident)
        try:
            with t.update_schema() as u:
                u.union_by_name(table.schema)
            t = cat.load_table(ident)
            if mode == "overwrite":
                t.overwrite(table)
            else:
                t.append(table)
        except Exception:  # noqa: BLE001 - incompatible type change on a rebuilt table: recreate it
            if mode != "overwrite":
                raise
            cat.drop_table(ident)
            t = cat.create_table(ident, schema=table.schema)
            t.append(table)
    else:
        t = cat.create_table(ident, schema=table.schema)
        t.append(table)
    return t


def read(layer: str, name: str) -> pa.Table:
    return catalog().load_table(f"{layer}.{name}").scan().to_arrow()


def list_tables() -> list[str]:
    cat = catalog()
    out = []
    for ns in LAYERS:
        for ident in cat.list_tables(ns):
            out.append(".".join(ident))
    return out


def duck(persist: bool = False) -> duckdb.DuckDBPyConnection:
    """DuckDB connection with one view per Iceberg table (layer__name), over iceberg_scan."""
    con = duckdb.connect(str(DUCKDB_FILE) if persist else ":memory:")
    con.sql("INSTALL iceberg; LOAD iceberg;")
    cat = catalog()
    for ns in LAYERS:
        con.sql(f"CREATE SCHEMA IF NOT EXISTS {ns}")
        for ident in cat.list_tables(ns):
            t = cat.load_table(ident)
            con.sql(f"CREATE OR REPLACE VIEW {ns}.{ident[-1]} AS SELECT * FROM iceberg_scan('{t.metadata_location}')")
    return con


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def tbl(rel) -> pa.Table:
    """Materialise a DuckDB relation as an Arrow table (DuckDB >= 1.4 returns a reader from .arrow())."""
    a = rel.arrow()
    return a.read_all() if isinstance(a, pa.RecordBatchReader) else a
