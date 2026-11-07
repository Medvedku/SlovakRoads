"""Load bridge conditions from historical exports (2012-2021 era) into the DB.

These exports have one row per bridge, no DC ids, and differently named
condition columns. The loader maps them onto the unified names and appends
one conditions row per bridge and year.

Usage:
    mosty history data/ssc/2017_ssc_export.csv
"""

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from mosty.export import (
    conditions_per_bridge,
    load_export,
    snake,
    split_rows,
)

# unified conditions column -> possible column names in old exports
CONDITION_MAP = {
    "stavebno_technický_stav": ["stavebno_technický_stav", "stavebný_stav"],
    "normána_zaťažiteľnost": [
        "normána_zaťažiteľnost", "zaťažiteľnosť_normálna",
        "zaťažiteľnost_normálna", "zatazitelnost_normalna",
    ],
    "výhradná_zaťažiteľnosť": [
        "výhradná_zaťažiteľnosť", "zaťažiteľnosť_výhradná",
        "zaťažiteľnost_výhradná", "zatazitelnost_vyhradna",
    ],
    "výnimočná_zaťažiteľnosť": [
        "výnimočná_zaťažiteľnosť", "zaťažiteľnosť_výnimočná",
        "zaťažiteľnost_výnimočná", "zatazitelnost_vynimocna",
    ],
}
BRIDGE_ID_CANDIDATES = [
    "identifikačné_číslo_mosta",  # 2013-2017
    "identifikačné_číslo_mostu",  # 2018-2021
    "id_číslo_mostu",             # 2012
]

NUMERIC = set(CONDITION_MAP) - {"stavebno_technický_stav"}

# pre-2012 exports have no M#### ids; 2012 carries the old evidence number
DEFAULT_BRIDGE_MAP_CSV = Path("data/ssc/2012_ssc_export.csv")


def norm_road(t, c):
    return (str(t).strip(), str(c).strip().lstrip("0") or "0")


def norm_ev(e):
    e = str(e).strip()
    return e.lstrip("0") or "0" if e.isdigit() else e


def build_bridge_map(csv_path: Path) -> dict:
    """(trieda, číslo, evidenčné číslo staré) -> M#### from the 2012 export."""
    d12 = pd.read_csv(csv_path, sep=";", dtype=str)
    keys = [
        norm_road(t, c) + (norm_ev(e),)
        for t, c, e in zip(d12["Trieda CK"], d12["číslo CK"],
                           d12["evidenčné číslo - staré"])
    ]
    mapping = pd.Series(d12["ID číslo mostu"].values, index=keys)
    grouped = mapping.groupby(level=0).agg(lambda s: set(s.dropna()))
    unique = grouped[grouped.map(len) == 1].map(lambda s: next(iter(s)))
    return unique.to_dict()


def norm_stav_2011(v):
    """2011 uses lowercase plus two categories the newer system dropped."""
    s = str(v).strip().lower()
    if s in ("", "nan", "none"):
        return None
    return {"výborný": "Bezchybný", "neudaný": "Neudaný"}.get(s, s.capitalize())


def resolve(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def is_modern_format(path: Path) -> bool:
    """2022+ exports have id_mosta/id_dc columns (Most/DC split rows)."""
    header = pd.read_csv(path, sep=";", nrows=0)
    return "ID mosta" in header.columns


def load_history(path: Path, bridge_map_csv: Path = DEFAULT_BRIDGE_MAP_CSV) -> pd.DataFrame:
    if is_modern_format(path):
        # 2022-2024: same format as init/update, reuse the shared loader
        raw = load_export(path)
        _, dc_rows = split_rows(raw)
        cond = conditions_per_bridge(dc_rows)
        return cond.rename(columns={"bridge_id": "bridge_id"})

    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8")
    df.columns = [snake(c) for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c]]

    bridge_col = resolve(df, BRIDGE_ID_CANDIDATES)
    is_2011 = bridge_col is None and "evidenčné_číslo_mostu" in df.columns
    if is_2011:
        bridge_map = build_bridge_map(bridge_map_csv)
        keys = [
            norm_road(t, c) + (norm_ev(e),)
            for t, c, e in zip(df["trieda_ck"], df["číslo_ck"],
                               df["evidenčné_číslo_mostu"])
        ]
        bridges = pd.Series(keys).map(bridge_map)
    elif bridge_col is None:
        sys.exit(f"error: no bridge id column found in {path.name}")
    else:
        bridges = df[bridge_col]
    out = pd.DataFrame({"bridge_id": bridges})

    for unified, candidates in CONDITION_MAP.items():
        col = resolve(df, candidates)
        if col is None:
            out[unified] = pd.NA
            continue
        if unified in NUMERIC:
            cleaned = (
                df[col].str.replace("\xa0", "")
                .str.replace(" ", "")
                .str.replace(",", ".")
            )
            out[unified] = pd.to_numeric(cleaned, errors="coerce")
        else:
            out[unified] = df[col]
    if is_2011:
        out["stavebno_technický_stav"] = out["stavebno_technický_stav"].map(norm_stav_2011)
    return out.dropna(subset=["bridge_id"])


def build(db_path: Path, csv_path: Path, year: int,
          bridge_map_csv: Path = DEFAULT_BRIDGE_MAP_CSV) -> None:
    import sqlite3

    if not db_path.exists():
        sys.exit(f"error: database {db_path} does not exist, run init first")

    hist = load_history(csv_path, bridge_map_csv)
    hist = hist.groupby("bridge_id", sort=False, as_index=False).first()
    hist.insert(1, "year", year)

    con = sqlite3.connect(db_path)
    known = {r[0] for r in con.execute("SELECT id_mosta FROM bridges")}
    already = {r[0] for r in con.execute(
        "SELECT bridge_id FROM conditions WHERE year = ?", (year,)
    )}
    if already:
        sys.exit(f"error: year {year} already loaded ({len(already)} rows) - refusing")

    matched = hist[hist["bridge_id"].isin(known)]
    skipped = len(hist) - len(matched)

    cols = ["bridge_id", "year", *CONDITION_MAP]
    matched[cols].to_sql("conditions", con, if_exists="append", index=False)

    meta = {
        f"history_{year}_file": csv_path.name,
        f"history_{year}_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        f"history_{year}_imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        f"history_{year}_rows": str(len(matched)),
        f"history_{year}_skipped_unknown_bridges": str(skipped),
    }
    con.executemany("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", meta.items())
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM conditions").fetchone()[0]
    con.close()

    print(f"{csv_path.name} -> year {year}: {len(matched)} rows inserted, "
          f"{skipped} skipped (bridge unknown in this db), conditions total: {total}")


if __name__ == "__main__":
    sys.exit(build(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])))
