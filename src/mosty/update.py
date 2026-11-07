"""Yearly update: merge a new export into an existing database.

Usage:
    mosty update data/ssc/2026_ssc_export.csv
    mosty update https://.../sr_co_report_mostypk_2026-01-01.csv
    mosty update            # prompts for a link or path
"""

import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

from mosty.db import SCHEMA_VERSION, count_rows, source_meta, write_metadata
from mosty.export import (
    BRIDGE_COLS,
    DC_COLS,
    LOCATION_COLS,
    conditions_per_bridge,
    load_export,
    split_rows,
)

USER_AGENT = "Mozilla/5.0"


def fetch_csv(source: str) -> tuple[Path, int]:
    """Resolve a local path or URL to a CSV file; returns (path, year)."""
    if source.startswith("http://") or source.startswith("https://"):
        name = Path(urlparse(source).path).name
        year_match = __import__("re").search(r"(20\d\d)", name)
        if not year_match:
            sys.exit(f"error: cannot guess year from URL file name: {name}")
        year = int(year_match.group(1))
        dest = Path("data/ssc") / f"{year}_ssc_export.csv"
        if dest.exists():
            print(f"{year}: {dest} exists, using local copy (delete it to re-download)")
            return dest, year
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"{year}: downloading {source} ...")
        tmp = dest.with_suffix(".part")
        try:
            req = Request(source, headers={"User-Agent": USER_AGENT})
            with urlopen(req) as response, tmp.open("wb") as out:
                out.write(response.read())
            tmp.replace(dest)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            sys.exit(f"error: download failed - {e}")
        _fix_encoding(dest)
        print(f"{year}: saved to {dest} ({dest.stat().st_size:,} bytes)")
        return dest, year

    path = Path(source)
    if not path.exists():
        sys.exit(f"error: file not found: {path}")
    import re

    year_match = re.search(r"(20\d\d)", path.name)
    if not year_match:
        sys.exit(f"error: cannot guess year from file name, pass --year")
    return path, int(year_match.group(1))


def _fix_encoding(path: Path) -> None:
    data = path.read_bytes()
    try:
        data.decode("utf-8")
        return
    except UnicodeDecodeError:
        pass
    try:
        converted = data.decode("cp1250").encode("utf-8")
    except UnicodeDecodeError:
        sys.exit(f"error: cannot decode {path} as utf-8 or cp1250")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(converted)
    tmp.replace(path)


def diff(new: pd.DataFrame, con: sqlite3.Connection) -> tuple[set, set]:
    known = {r[0] for r in con.execute("SELECT id_mosta FROM bridges WHERE archived = 0")}
    incoming = set(new["bridge_id"].dropna().unique())
    return incoming - known, known - incoming


def report(new_bridges: set, gone_bridges: set, changed: int) -> None:
    print(f"new bridges:      {len(new_bridges)}")
    print(f"bridges gone:     {len(gone_bridges)}  (will be archived)")
    print(f"condition changes since previous year: {changed}")
    for label, ids in (("new", new_bridges), ("gone", gone_bridges)):
        if ids:
            sample = sorted(ids)[:10]
            print(f"  {label}: {', '.join(sample)}{' ...' if len(ids) > 10 else ''}")


def changed_conditions(con: sqlite3.Connection, year: int,
                       cond: pd.DataFrame) -> int:
    prev = {
        r[0]: r[1]
        for r in con.execute(
            "SELECT bridge_id, stavebno_technický_stav FROM conditions "
            "WHERE year = (SELECT MAX(year) FROM conditions)"
        )
    }
    new = dict(zip(cond["bridge_id"], cond["stavebno_technický_stav"]))
    return sum(
        1 for b in set(prev) & set(new)
        if str(prev[b]) != str(new[b]) and not (pd.isna(prev[b]) and pd.isna(new[b]))
    )


def apply(con: sqlite3.Connection, csv_path: Path, year: int,
          raw: pd.DataFrame, most_rows: pd.DataFrame, dc_rows: pd.DataFrame,
          new_bridges: set, gone_bridges: set) -> None:
    bridges = most_rows.groupby("bridge_id", sort=False, as_index=False).first()
    dcs = dc_rows.groupby("id_dc", sort=False, as_index=False).first()
    locations = most_rows.groupby(
        ["bridge_id", "úsek_id"], sort=False, as_index=False
    ).first()

    # upsert bridges
    cols = ["bridge_id", *BRIDGE_COLS]
    for row in bridges[cols].itertuples(index=False, name=None):
        values = [None if pd.isna(v) else v for v in row[1:]]
        con.execute(
            f"""INSERT INTO bridges (id_mosta, {', '.join(BRIDGE_COLS)})
                VALUES ({', '.join('?' * (len(cols)))})
                ON CONFLICT(id_mosta) DO UPDATE SET
                {', '.join(f'{c} = excluded.{c}' for c in BRIDGE_COLS)},
                archived = 0, archived_year = NULL""",
            (row[0], *values),
        )

    # archive bridges missing from the new export
    con.executemany(
        "UPDATE bridges SET archived = 1, archived_year = ? WHERE id_mosta = ?",
        [(year, b) for b in gone_bridges],
    )

    # upsert dcs (skip dcs of unknown bridges - they are inserted with their bridge)
    dc_cols = ["id_dc", "bridge_id", *DC_COLS]
    for row in dcs[dc_cols].itertuples(index=False, name=None):
        values = [None if pd.isna(v) else v for v in row[2:]]
        con.execute(
            f"""INSERT INTO dcs (id_dc, bridge_id, {', '.join(DC_COLS)})
                VALUES ({', '.join('?' * len(dc_cols))})
                ON CONFLICT(id_dc) DO UPDATE SET
                {', '.join(f'{c} = excluded.{c}' for c in DC_COLS)}""",
            (row[0], row[1], *values),
        )

    # locations are fully derived - replace wholesale
    con.execute("DELETE FROM locations")
    con.executemany(
        f"INSERT INTO locations (bridge_id, {', '.join(LOCATION_COLS)}) "
        f"VALUES ({', '.join('?' * (1 + len(LOCATION_COLS)))})",
        [
            tuple(None if pd.isna(v) else v for v in row)
            for row in locations[["bridge_id", *LOCATION_COLS]].itertuples(
                index=False, name=None
            )
        ],
    )

    # append conditions for this year
    cond = conditions_per_bridge(dc_rows)
    cond.insert(1, "year", year)
    existing_years = {r[0] for r in con.execute("SELECT DISTINCT year FROM conditions")}
    if year in existing_years:
        sys.exit(f"error: conditions for {year} already exist - refusing")
    cond.to_sql("conditions", con, if_exists="append", index=False)

    meta = source_meta(csv_path, year)
    meta.update({
        "schema_version": str(SCHEMA_VERSION),
        "last_update": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bridges": str(con.execute("SELECT COUNT(*) FROM bridges").fetchone()[0]),
        "dcs": str(con.execute("SELECT COUNT(*) FROM dcs").fetchone()[0]),
        "locations": str(con.execute("SELECT COUNT(*) FROM locations").fetchone()[0]),
    })
    write_metadata(con, meta)
    con.commit()


def run(source: str, db_path: Path, year: int | None, assume_yes: bool) -> None:
    if not db_path.exists():
        sys.exit(f"error: database {db_path} does not exist - run init/rebuild first")

    csv_path, csv_year = fetch_csv(source)
    if year is not None:
        csv_year = year

    con = sqlite3.connect(db_path)
    meta = dict(con.execute("SELECT key, value FROM metadata"))
    db_year = int(meta.get("source_year", 0))
    if csv_year <= db_year:
        con.close()
        sys.exit(
            f"error: database holds year {db_year}, update export is {csv_year} - "
            "the update must be newer"
        )

    raw = load_export(csv_path)
    most_rows, dc_rows = split_rows(raw)
    cond = conditions_per_bridge(dc_rows)
    new_bridges, gone_bridges = diff(raw, con)
    changed = changed_conditions(con, csv_year, cond)

    report(new_bridges, gone_bridges, changed)
    if not assume_yes:
        answer = input("apply this update? [y/N] ")
        if answer.strip().lower() != "y":
            con.close()
            print("update cancelled")
            return

    apply(con, csv_path, csv_year, raw, most_rows, dc_rows,
          new_bridges, gone_bridges)
    print("counts:", "  ".join(f"{k}: {v}" for k, v in count_rows(con).items()))
    con.close()
    print(f"database updated to year {csv_year}")
