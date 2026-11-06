"""Build the bridge database (SQLite) from an SSC export.

Usage:
    mosty init data/ssc/2025_ssc_export.csv
"""

import hashlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = 1

# Column groups define where each attribute belongs in the database.
BRIDGE_COLS = [
    "trieda_pk", "číslo_pk", "názov_mosta", "správcovské_číslo",
    "rok_postavenia", "zaťažovacia_trieda_stn", "počet_otvorov",
    "dĺžka_premostenia", "dĺžka_nosnej_konštrukcie", "volná_šírka_mosta",
    "šírka_medzi_obrubami", "plocha_mosta", "plocha_nosnej_konštrukcie",
    "okres",
]
DC_COLS = [
    "stavebno_technický_stav", "druh_konštrukcie", "material",
    "normána_zaťažiteľnost", "výhradná_zaťažiteľnosť",
    "výnimočná_zaťažiteľnosť", "ojedinelá_zaťažiteľnosť",
    "zaťažiteľnosť_na_nápravu", "spôsob_stanovenia", "predmet_premostenia",
    "longitude", "latitude", "vyska", "správca_dc_mostu", "vlastník_dc_mostu",
]
LOCATION_COLS = [
    "úsek_id", "smer_úseku_pk", "typ_úseku_pk", "počiatočný_uzol_úseku_pk",
    "koncový_uzol_úseku_pk", "správca_úseku_pk", "vlastník_úseku_pk",
    "úsekové_staničenie_začiatku_dc", "kilometrovníkové_staničenie_začiatku_dc",
    "kumulatívne_staničenie_začiatku_dc", "poradie",
]
# columns converted to numbers on import; everything else stays TEXT
NUMERIC_COLS = {
    "rok_postavenia", "počet_otvorov", "dĺžka_premostenia",
    "dĺžka_nosnej_konštrukcie", "volná_šírka_mosta", "šírka_medzi_obrubami",
    "plocha_mosta", "plocha_nosnej_konštrukcie", "longitude", "latitude",
    "vyska", "normána_zaťažiteľnost", "výhradná_zaťažiteľnosť",
    "výnimočná_zaťažiteľnosť", "ojedinelá_zaťažiteľnosť",
    "zaťažiteľnosť_na_nápravu", "úsekové_staničenie_začiatku_dc",
    "kilometrovníkové_staničenie_začiatku_dc",
    "kumulatívne_staničenie_začiatku_dc", "poradie",
}
INTEGER_COLS = {"rok_postavenia", "počet_otvorov", "poradie"}
# fix source typos / unify names after generic snake-casing
RENAME = {"pocha_mosnej_konštrukcie": "plocha_nosnej_konštrukcie"}

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
    plocha_mosta REAL, plocha_nosnej_konštrukcie REAL, okres TEXT
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


def snake(h: str) -> str:
    h = re.sub(r"\s*/\s*(m2|m|t|km)\s*$", "", h.strip())
    h = "_".join(h.replace("-", " ").split()).lower()
    h = h.replace("most_/dc", "most_dc")
    return RENAME.get(h, h)


def load_export(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8")
    df.columns = [snake(c) for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c]]
    df = df.drop(columns=["most_dc"])
    df["bridge_id"] = df["id_mosta"].fillna(
        df["id_dc"].str.replace(r"\.\d+$", "", regex=True)
    )
    for col in NUMERIC_COLS & set(df.columns):
        cleaned = (
            df[col].str.replace("\xa0", "").str.replace(" ", "").str.replace(",", ".")
        )
        df[col] = pd.to_numeric(cleaned, errors="coerce")
    for col in INTEGER_COLS & set(df.columns):
        df[col] = df[col].astype("Int64")
    expected = {"id_mosta", "id_dc", "bridge_id", *BRIDGE_COLS, *DC_COLS, *LOCATION_COLS}
    for col in expected - set(df.columns):
        df[col] = pd.NA
    return df


def build(db_path: Path, csv_path: Path, year: int) -> None:
    raw = load_export(csv_path)

    most_rows = raw[raw["id_mosta"].notna()]
    dc_rows = raw[raw["id_dc"].notna()]

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

    cond = dc_rows[["bridge_id", "stavebno_technický_stav", *DC_COLS[3:8]]].copy()
    # one row per bridge: DCs of the same bridge carry the same values,
    # except stav on multi-DC bridges - keep all distinct values there
    cond = cond.groupby("bridge_id", sort=False, as_index=False).first()
    multi = dc_rows.groupby("bridge_id")["stavebno_technický_stav"].nunique()
    multi = multi[multi > 1].index
    if len(multi):
        joined = (
            dc_rows[dc_rows["bridge_id"].isin(multi)]
            .groupby("bridge_id")["stavebno_technický_stav"]
            .agg(lambda s: " | ".join(sorted(set(s.dropna()))))
        )
        cond.loc[cond["bridge_id"].isin(multi), "stavebno_technický_stav"] = cond[
            "bridge_id"
        ].map(joined)
    cond.insert(1, "year", year)
    cond.to_sql("conditions", con, if_exists="append", index=False)

    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "source_file": csv_path.name,
        "source_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "source_year": str(year),
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bridges": str(len(bridges)),
        "dcs": str(len(dcs)),
        "locations": str(len(locations)),
    }
    con.executemany("INSERT INTO metadata (key, value) VALUES (?, ?)", meta.items())
    con.commit()

    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("bridges", "dcs", "locations", "conditions")
    }
    orphans = con.execute(
        "SELECT COUNT(*) FROM dcs WHERE bridge_id NOT IN (SELECT id_mosta FROM bridges)"
    ).fetchone()[0]
    con.close()

    print(f"database: {db_path}")
    print("  ".join(f"{k}: {v}" for k, v in counts.items()))
    if orphans:
        print(f"WARNING: {orphans} dcs reference unknown bridges")
