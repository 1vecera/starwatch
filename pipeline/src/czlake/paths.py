"""Filesystem layout of the local lakehouse (outside every worktree, Git-ignored)."""
from pathlib import Path
import os

PROJECT = Path(os.environ.get("CZLAKE_PROJECT", "/home/vecera/code/agents007-hackathon"))
DATA = PROJECT / "data"
LAKE = DATA / "lake"
RAW = LAKE / "raw"
WAREHOUSE = LAKE / "warehouse"
CATALOG_DB = LAKE / "catalog.db"
DUCKDB_FILE = LAKE / "lake.duckdb"
LEDGER = DATA / "ledger.csv"
MANIFEST = RAW / "_manifest.jsonl"
DOCS = PROJECT / "docs" / "explore"

for p in (RAW, WAREHOUSE, DOCS):
    p.mkdir(parents=True, exist_ok=True)
