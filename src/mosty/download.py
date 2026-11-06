"""Download SSC bridge exports listed in sources.toml.

Usage:
    mosty download            # download missing files
    mosty download --force    # re-download even if file exists
"""

import argparse
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path("sources.toml")


def fix_encoding(path: Path) -> str:
    """Recode file to UTF-8 if needed. Returns 'utf-8', 'converted' or 'failed'."""
    data = path.read_bytes()
    try:
        data.decode("utf-8")
        return "utf-8"  # already UTF-8
    except UnicodeDecodeError:
        pass
    try:
        converted = data.decode("cp1250").encode("utf-8")
    except UnicodeDecodeError:
        return "failed"
    tmp = path.with_suffix(".part")
    tmp.write_bytes(converted)
    tmp.replace(path)
    return "converted"


def download_all(config_path: Path = CONFIG_PATH, force: bool = False) -> None:
    with config_path.open("rb") as f:
        config = tomllib.load(f)

    dest = Path(config["download"]["dest"])
    sources = config["source"]
    dest.mkdir(parents=True, exist_ok=True)

    for source in sources:
        year, url = source["year"], source["url"]
        target = dest / f"{year}_ssc_export.csv"

        if not url:
            print(f"{year}: no URL in config, skipping")
            continue
        if target.exists() and not force:
            status = fix_encoding(target)
            print(f"{year}: {target.name} exists, encoding {status}")
            continue

        print(f"{year}: downloading {url} ...")
        tmp = target.with_suffix(".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request) as response, tmp.open("wb") as out:
                out.write(response.read())
            tmp.replace(target)
        except (urllib.error.URLError, OSError) as e:
            print(f"{year}: FAILED - {e}")
            tmp.unlink(missing_ok=True)
            continue
        print(f"{year}: saved to {target} ({target.stat().st_size:,} bytes)")
        print(f"{year}: encoding {fix_encoding(target)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SSC bridge export tools")
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="download CSV exports listed in sources.toml")
    dl.add_argument("--force", action="store_true", help="re-download existing files")
    dl.add_argument("--config", type=Path, default=CONFIG_PATH, help="config path")

    args = parser.parse_args()
    if args.command == "download":
        download_all(config_path=args.config, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
