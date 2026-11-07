"""Fetch the latest published database release from GitHub.

The ground-zero release ships the asset `mosty.db`; updated releases ship
`mosty_{year}.db`. The fetched file is renamed to `data/mosty_{source_year}.db`
according to its own metadata, so the working file name always reflects the
data it holds.
"""

import json
import shutil
import sqlite3
import sys
import urllib.request
from pathlib import Path

from mosty.db import SCHEMA_VERSION

API_LATEST = "https://api.github.com/repos/Medvedku/SlovakRoads/releases/latest"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}


def latest_db_asset() -> tuple[str, str]:
    """Return (asset name, download url) of the newest release's .db asset."""
    req = urllib.request.Request(API_LATEST, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            release = json.load(response)
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot reach GitHub releases - {e}")

    if "assets" not in release:
        sys.exit(f"error: GitHub says: {release.get('message', release)}")
    assets = [a for a in release["assets"] if a["name"].endswith(".db")]
    if not assets:
        sys.exit(f"error: release {release.get('tag_name')} has no .db asset")
    return assets[0]["name"], assets[0]["browser_download_url"]


def fetch_latest_db(dest_dir: Path = Path("data")) -> Path:
    """Download the latest release database, return its local path."""
    name, url = latest_db_asset()
    tmp = dest_dir / f"{name}.part"
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"fetching release asset {name} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"error: download failed - {e}")

    # sanity: right schema and a readable source year
    try:
        con = sqlite3.connect(tmp)
        version = con.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        year = con.execute("SELECT value FROM metadata WHERE key='source_year'").fetchone()
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
        tmp.unlink()
        print(f"{dest} exists, using local copy (delete it to re-download)")
        return dest
    tmp.replace(dest)
    print(f"saved to {dest} ({dest.stat().st_size:,} bytes, source year {year[0]})")
    return dest
