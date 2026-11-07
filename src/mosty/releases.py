"""Fetch the newest published mosty database from GitHub releases.

Databases are published as release assets: the ground-zero release ships
`mosty.db`, updated releases ship `mosty_{year}.db`. Every release of the
repo is searched (not just the latest one), so assets the repo may grow
for other databases are simply ignored. The user is asked before anything
is downloaded; the fetched file is renamed to `data/mosty_{source_year}.db`
according to its own metadata, so the working file name always reflects
the data it holds.
"""

import json
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mosty.db import SCHEMA_VERSION

API_RELEASES = "https://api.github.com/repos/Medvedku/SlovakRoads/releases"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}

# mosty.db (ground zero) or mosty_YYYY.db (yearly updates); anything else
# (databases of other things) is ignored
ASSET_NAME = re.compile(r"mosty(_\d{4})?\.db")


def list_db_assets() -> list[dict]:
    """All mosty database assets across every release of the repo."""
    assets, page = [], 1
    while True:
        req = urllib.request.Request(
            f"{API_RELEASES}?per_page=100&page={page}", headers=HEADERS
        )
        try:
            with urllib.request.urlopen(req) as response:
                releases = json.load(response)
        except urllib.error.URLError as e:
            sys.exit(f"error: cannot reach GitHub releases - {e}")
        if isinstance(releases, dict):  # error payload, not a release list
            sys.exit(f"error: GitHub says: {releases.get('message', releases)}")
        for release in releases:
            for asset in release.get("assets", []):
                if ASSET_NAME.fullmatch(asset["name"]):
                    assets.append({
                        "name": asset["name"],
                        "url": asset["browser_download_url"],
                        "release": release.get("tag_name") or release.get("name") or "?",
                        "published": release.get("published_at") or "",
                    })
        if len(releases) < 100:
            return assets
        page += 1


def asset_year(name: str) -> int:
    """Year encoded in the asset name; 0 for the unversioned mosty.db."""
    match = re.search(r"_(\d{4})", name)
    return int(match.group(1)) if match else 0


def newest_db_asset() -> dict:
    """Newest mosty database asset by year, then by release date."""
    assets = list_db_assets()
    if not assets:
        sys.exit("error: no mosty database asset found in any release")
    return max(assets, key=lambda a: (asset_year(a["name"]), a["published"]))


def fetch_release_db(dest_dir: Path = Path("data"),
                     assume_yes: bool = False) -> Path | None:
    """Find the newest release database and download it; return its path.

    Returns None when the user declines. An existing local copy in
    dest_dir is reused instead of downloading.
    """
    asset = newest_db_asset()
    print(f"newest release database: {asset['name']} "
          f"(release {asset['release']}, "
          f"published {asset['published'][:10] or '?'})")
    if not assume_yes and input("update this database? [y/N] ").strip().lower() != "y":
        return None

    if asset_year(asset["name"]):  # named mosty_YYYY.db - local shortcut
        dest = dest_dir / asset["name"]
        if dest.exists():
            print(f"{dest} exists, using local copy (delete it to re-download)")
            return dest

    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f"{asset['name']}.part"
    print(f"downloading {asset['url']} ...")
    try:
        req = urllib.request.Request(asset["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"error: download failed - {e}")

    # sanity: right schema and a readable source year
    try:
        con = sqlite3.connect(tmp)
        version = con.execute(
            "SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        year = con.execute(
            "SELECT value FROM metadata WHERE key='source_year'").fetchone()
        con.close()
    except sqlite3.DatabaseError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"error: downloaded file is not a valid mosty database - {e}")
    if not version or int(version[0]) != SCHEMA_VERSION:
        got = version[0] if version else "none"
        tmp.unlink(missing_ok=True)
        sys.exit(f"error: release has schema version {got}, code expects {SCHEMA_VERSION}")
    if not year:
        tmp.unlink(missing_ok=True)
        sys.exit("error: release database has no source_year in metadata")

    dest = dest_dir / f"mosty_{year[0]}.db"
    if dest.exists():
        tmp.unlink(missing_ok=True)
        print(f"{dest} exists, using local copy (delete it to re-download)")
        return dest
    tmp.replace(dest)
    print(f"saved to {dest} ({dest.stat().st_size:,} bytes, source year {year[0]})")
    return dest
