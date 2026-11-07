import re
import sys
from pathlib import Path

from mosty.db import build
from mosty.download import download_all
from mosty.history import build as build_history
from mosty.rebuild import run as rebuild
from mosty.releases import fetch_release_db
from mosty.update import run as update

DATA_DIR = Path("data")
DEFAULT_INIT_YEAR = 2025


def year_db(year: int) -> Path:
    """Default database path for a ground-zero build: data/mosty_{year}.db."""
    return DATA_DIR / f"mosty_{year}.db"


def latest_db() -> Path | None:
    """Newest data/mosty_YYYY.db by year, if any."""
    dbs = DATA_DIR.glob("mosty_[0-9][0-9][0-9][0-9].db")
    return max(dbs, key=lambda p: int(p.stem.rsplit("_", 1)[1]), default=None)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SSC bridge export tools")
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="download CSV exports listed in sources.toml")
    dl.add_argument("--force", action="store_true", help="re-download existing files")
    dl.add_argument("--config", type=Path, default=Path("sources.toml"), help="config path")

    init = sub.add_parser("init", help="build a fresh database from an export")
    init.add_argument("csv", type=Path, help="path to the SSC export CSV")
    init.add_argument("--db", type=Path, default=None,
                      help="database path (default: data/mosty_{year}.db)")
    init.add_argument("--year", type=int, help="export year (default: from filename)")

    hist = sub.add_parser("history", help="append conditions from a historical export (2011-2021)")
    hist.add_argument("csv", type=Path, help="path to the historical SSC export CSV")
    hist.add_argument("--db", type=Path, default=None,
                      help="database path (default: newest data/mosty_YYYY.db)")
    hist.add_argument("--year", type=int, help="export year (default: from filename)")

    rb = sub.add_parser("rebuild", help="full pipeline: download + init + history")
    rb.add_argument("--db", type=Path, default=None,
                   help="database path (default: data/mosty_{year}.db)")
    rb.add_argument("--year", type=int, default=DEFAULT_INIT_YEAR,
                    help="init year, the ground-zero export (default: 2025)")
    rb.add_argument("--config", type=Path, default=Path("sources.toml"), help="config path")

    up = sub.add_parser("update", help="merge a newer export into an existing database")
    up.add_argument("source", nargs="?", default=None,
                    help="path or URL of the new export (prompts if missing)")
    up.add_argument("--db", type=Path, default=None,
                    help="database path (default: newest data/mosty_YYYY.db, "
                         "or the latest GitHub release when --from-release)")
    up.add_argument("--from-release", action="store_true",
                    help="use the newest mosty_*.db release asset as the base "
                         "(searches all releases, asks first)")
    up.add_argument("--year", type=int, help="export year (default: from file name)")
    up.add_argument("--yes", action="store_true", help="apply without confirmation")

    args = parser.parse_args()
    if args.command in ("init", "history"):
        year = args.year if args.year is not None else _guess_year(args)
    if args.command == "download":
        download_all(config_path=args.config, force=args.force)
    elif args.command == "init":
        build(args.db or year_db(year), args.csv, year)
    elif args.command == "history":
        db = args.db or latest_db()
        if db is None:
            sys.exit("error: no data/mosty_YYYY.db found - run init/rebuild first "
                     "or pass --db")
        build_history(db, args.csv, year)
    elif args.command == "rebuild":
        rebuild(args.db or year_db(args.year), args.year, args.config)
    elif args.command == "update":
        db = args.db
        if db is None and args.from_release:
            db = fetch_release_db(assume_yes=args.yes)
            if db is None:
                print("update cancelled")
                return
        source = args.source
        if source is None:
            source = input("path or URL of the new export: ").strip()
            if not source:
                sys.exit("error: no source given")
        if db is None:
            db = latest_db()
        if db is None:
            sys.exit("error: no data/mosty_YYYY.db found - run rebuild first, "
                     "pass --db, or use --from-release")
        update(source, db, args.year, args.yes)


def _guess_year(args) -> int:
    match = re.search(r"(20\d\d)", args.csv.name)
    if not match:
        sys.exit("error: cannot guess year from filename, pass --year")
    return int(match.group(1))


if __name__ == "__main__":
    sys.exit(main())
