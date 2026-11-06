"""Full pipeline wrapper: download -> init -> history.

Usage:
    mosty rebuild
"""

import sys
import tomllib
from pathlib import Path

from mosty.db import build as build_db
from mosty.download import download_all
from mosty.history import build as build_history

# years loadable by the history loader (evidence-number / M#### era);
# 2022+ uses the Most/DC format and belongs to the future update command
SUPPORTED_HISTORY_YEARS = range(2011, 2022)


def run(db_path: Path, year: int, config_path: Path = Path("sources.toml")) -> None:
    if db_path.exists():
        sys.exit(f"error: {db_path} already exists - rebuild refuses to overwrite")
    if not config_path.exists():
        sys.exit(f"error: config {config_path} not found")

    download_all(config_path=config_path)

    with config_path.open("rb") as f:
        dest = Path(tomllib.load(f)["download"]["dest"])

    init_csv = dest / f"{year}_ssc_export.csv"
    if not init_csv.exists():
        sys.exit(f"error: {init_csv} missing after download, cannot init")
    print(f"\n=== init: {init_csv} ===")
    build_db(db_path, init_csv, year)

    loaded, skipped, failed = [], [], []
    for y in SUPPORTED_HISTORY_YEARS:
        if y >= year:
            continue
        csv = dest / f"{y}_ssc_export.csv"
        if not csv.exists():
            skipped.append(y)
            continue
        print(f"\n=== history: {csv} ===")
        try:
            build_history(db_path, csv, y)
            loaded.append(y)
        except SystemExit as e:
            print(f"warning: year {y} failed: {e}")
            failed.append(y)

    print("\n=== rebuild summary ===")
    print(f"database: {db_path}")
    print(f"init year: {year}")
    print(f"history loaded: {loaded}")
    if skipped:
        print(f"history skipped (file missing): {skipped}")
    if failed:
        print(f"history failed: {failed}")
