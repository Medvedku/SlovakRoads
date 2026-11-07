"""Build the bridge database (SQLite) from an SSC export.

Usage:
    mosty init data/ssc/2025_ssc_export.csv
"""

import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from mosty.export import (
    BRIDGE_COLS,
    DC_COLS,
    LOCATION_COLS,
    conditions_per_bridge,
    load_export,
    split_rows,
)

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS bridges (
    id_mosta TEXT PRIMARY KEY,
    trieda_pk TEXT, číslo_pk TEXT, názov_mosta TEXT, správcovské_číslo TEXT,
    rok_postavenia INTEGER, zaťažovacia_trieda_stn TEXT, počet_otvorov INTEGER,
    dĺžka_premostenia REAL, dĺžka_nosnej_konštrukcie REAL,
    volná_šírka_mosta REAL, šírka_medzi_obrubami REAL,
    plocha_mosta REAL, plocha_nosnej_konštrukcie REAL, okres TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_year INTEGER
);
CREATE TABLE IF NOT EXISTS dcs (
    id_dc TEXT PRIMARY KEY,
    bridge_id TEXT NOT NULL REFERENCES bridges(id_mosta),
    stavebno_technický_stav TEXT, druh_konštrukcie TEXT, material TEXT,
    normána_zaťažiteľnost REAL, výhradná_zaťažiteľnosť REAL,
    výnimočná_zaťažiteľnosť REAL, ojedinelá_zaťažiteľnosť REAL,
    zaťažiteľnosť_na_nápravu REAL, spôsob_stanovenia TEXT,
    predmet_premostenia TEXT, longitude REAL, latitude REAL, vyska REAL,
    správca_dc_mostu TEXT, vlastník_dc_mostu TEXT
);
CREATE TABLE IF NOT EXISTS locations (
    bridge_id TEXT NOT NULL REFERENCES bridges(id_mosta),
    úsek_id TEXT NOT NULL,
    smer_úseku_pk TEXT, typ_úseku_pk TEXT,
    počiatočný_uzol_úseku_pk TEXT, koncový_uzol_úseku_pk TEXT,
    správca_úseku_pk TEXT, vlastník_úseku_pk TEXT,
    úsekové_staničenie_začiatku_dc REAL,
    kilometrovníkové_staničenie_začiatku_dc REAL,
    kumulatívne_staničenie_začiatku_dc REAL,
    poradie INTEGER,
    PRIMARY KEY (bridge_id, úsek_id)
);
CREATE TABLE IF NOT EXISTS conditions (
    bridge_id TEXT NOT NULL REFERENCES bridges(id_mosta),
    year INTEGER NOT NULL,
    stavebno_technický_stav TEXT,
    normána_zaťažiteľnost REAL, výhradná_zaťažiteľnosť REAL,
    výnimočná_zaťažiteľnosť REAL, ojedinelá_zaťažiteľnosť REAL,
    zaťažiteľnosť_na_nápravu REAL,
    PRIMARY KEY (bridge_id, year)
);
"""


def write_metadata(con: sqlite3.Connection, meta: dict) -> None:
    con.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", meta.items())


def source_meta(csv_path: Path, year: int, prefix: str = "source") -> dict:
    return {
        f"{prefix}_file": csv_path.name,
        f"{prefix}_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        f"{prefix}_year": str(year),
        f"{prefix}_imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def count_rows(con: sqlite3.Connection) -> dict:
    return {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("bridges", "dcs", "locations", "conditions")
    }


def build(db_path: Path, csv_path: Path, year: int) -> None:
    raw = load_export(csv_path)
    most_rows, dc_rows = split_rows(raw)

    bridges = most_rows.groupby("bridge_id", sort=False, as_index=False).first()
    dcs = dc_rows.groupby("id_dc", sort=False, as_index=False).first()
    locations = most_rows.groupby(
        ["bridge_id", "úsek_id"], sort=False, as_index=False
    ).first()

    if db_path.exists():
        sys.exit(f"error: {db_path} already exists - init refuses to overwrite")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    bridges[["bridge_id", *BRIDGE_COLS]].rename(
        columns={"bridge_id": "id_mosta"}
    ).to_sql("bridges", con, if_exists="append", index=False)
    dcs[["id_dc", "bridge_id", *DC_COLS]].to_sql(
        "dcs", con, if_exists="append", index=False
    )
    locations[["bridge_id", *LOCATION_COLS]].to_sql(
        "locations", con, if_exists="append", index=False
    )

    cond = conditions_per_bridge(dc_rows)
    cond.insert(1, "year", year)
    cond.to_sql("conditions", con, if_exists="append", index=False)

    meta = source_meta(csv_path, year)
    meta.update({
        "schema_version": str(SCHEMA_VERSION),
        "bridges": str(len(bridges)),
        "dcs": str(len(dcs)),
        "locations": str(len(locations)),
    })
    write_metadata(con, meta)
    con.commit()

    counts = count_rows(con)
    orphans = con.execute(
        "SELECT COUNT(*) FROM dcs WHERE bridge_id NOT IN (SELECT id_mosta FROM bridges)"
    ).fetchone()[0]
    con.close()

    print(f"database: {db_path}")
    print("  ".join(f"{k}: {v}" for k, v in counts.items()))
    if orphans:
        print(f"WARNING: {orphans} dcs reference unknown bridges")
