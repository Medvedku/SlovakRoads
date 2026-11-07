"""Shared loader for the 2022+ export format (Most/DC split rows).

Used by both `init` (ground zero) and `update` (yearly merge).
"""

import re
from pathlib import Path

import pandas as pd

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

CONDITION_COLS = [
    "stavebno_technický_stav", "normána_zaťažiteľnost",
    "výhradná_zaťažiteľnosť", "výnimočná_zaťažiteľnosť",
    "ojedinelá_zaťažiteľnosť", "zaťažiteľnosť_na_nápravu",
]


def snake(h: str) -> str:
    h = re.sub(r"\s*/\s*(m2|m|t|km)\s*$", "", h.strip())
    h = "_".join(h.replace("-", " ").split()).lower()
    h = h.replace("most_/dc", "most_dc")
    return RENAME.get(h, h)


def read_export_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Parse the export and drop malformed rows (field count != header)."""
    import csv

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        rows, dropped = [], 0
        for row in reader:
            if len(row) == len(header):
                rows.append(row)
            else:
                dropped += 1
    if dropped:
        print(f"warning: {path.name}: dropped {dropped} malformed row(s) "
              f"(field count mismatch)")
    return header, rows


def load_export(path: Path) -> pd.DataFrame:
    header, rows = read_export_rows(path)
    df = pd.DataFrame(rows, columns=header)
    df.columns = [snake(c) for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c]]
    df = df.drop(columns=["most_dc"], errors="ignore")
    # empty id fields are missing, not the bridge "" (csv module keeps "")
    df["id_mosta"] = df["id_mosta"].replace("", pd.NA)
    df["id_dc"] = df["id_dc"].replace("", pd.NA)
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
    # blank text cells are missing data, not empty strings (legacy-year
    # loaders store them as NULL; keep the two consistent)
    obj_cols = df.select_dtypes(include="object").columns
    df[obj_cols] = df[obj_cols].replace("", pd.NA)
    expected = {"id_mosta", "id_dc", "bridge_id", *BRIDGE_COLS, *DC_COLS, *LOCATION_COLS}
    for col in expected - set(df.columns):
        df[col] = pd.NA
    return df


def split_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Most rows carry bridge data, DC rows carry unit data."""
    return df[df["id_mosta"].notna()], df[df["id_dc"].notna()]


def coalesce(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """One row per key group, first non-null value per column."""
    return df.groupby(keys, sort=False, as_index=False).first()


def conditions_per_bridge(dc_rows: pd.DataFrame) -> pd.DataFrame:
    """One conditions row per bridge from DC rows.

    DCs of the same bridge normally carry the same values; when stav
    differs across DCs of one bridge, keep all distinct values joined
    with ' | '.
    """
    cond = dc_rows[["bridge_id", *CONDITION_COLS]].copy()
    cond = coalesce(cond, ["bridge_id"])
    multi = dc_rows.groupby("bridge_id")["stavebno_technický_stav"].nunique()
    multi = multi[multi > 1].index
    if len(multi):
        joined = (
            dc_rows[dc_rows["bridge_id"].isin(multi)]
            .groupby("bridge_id")["stavebno_technický_stav"]
            .agg(lambda s: " | ".join(sorted(set(s.dropna()))))
        )
        cond.loc[cond["bridge_id"].isin(multi), "stavebno_technický_stav"] = (
            cond["bridge_id"].map(joined)
        )
    return cond
