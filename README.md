# SlovakRoads

Database of road bridges on Slovak roads (*mosty* = bridges), built from public
exports of the Slovak road administration. One command builds a SQLite database
with every bridge, its dilatation units, placement on road sections, and a
year-by-year condition history from 2011 on.

## Data source

All data comes from public CSV exports of **SSC — Slovenská správa ciest**
(Slovak National Road Administration), published in their road database
[CDB](https://www.cdb.sk). Yearly exports (2010–2026) are used; they are
Windows-1250 encoded, semicolon-delimited, and get converted to UTF-8
automatically during download.

The CSV files are **not** stored in this repository — download links live in
`sources.toml`, files land in `data/ssc/` as `{year}_ssc_export.csv`.
Built databases are published as GitHub releases — see the releases page
for the latest one.

## Setup

Requires [uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

## Usage

```sh
uv run mosty rebuild
```

That is the whole pipeline, equivalent to running the three steps below
in order. The database is written to `data/mosty_{year}.db` (named by the
init year, default 2025); rebuild refuses to overwrite an existing file,
so delete the old one first when rebuilding.

### Step by step

**1. Download the exports** listed in `sources.toml` (year + URL per entry):

```sh
uv run mosty download            # skips files that already exist
uv run mosty download --force    # re-download
```

Files are saved as `data/ssc/{year}_ssc_export.csv` and recoded from
Windows-1250 to UTF-8 automatically, whether freshly downloaded or already
on disk.

**2. Build the ground-zero database** from the current export:

```sh
uv run mosty init data/ssc/2025_ssc_export.csv
```

Defaults to `data/mosty_2025.db`, named by the export year.

**3. Append condition history** from older exports (2011–2024 era):

```sh
uv run mosty history data/ssc/2017_ssc_export.csv
```

Defaults to the newest `data/mosty_YYYY.db`; pass `--db` to pick another.

Each year loads once; loading an already-present year is refused. The 2010
export stays out on purpose: its object IDs were renumbered by 2011, so less
than 10% of bridges can be mapped — not worth the noise.

### Yearly update (2022+ format)

Merge a newer export into an existing database. The base database stays
untouched — the result is always a **new file named by the year it now
holds**:

```sh
# fetch the newest published mosty_*.db as the base
uv run mosty update --from-release

# or start from a local database (defaults to the newest data/mosty_YYYY.db)
uv run mosty update data/ssc/2026_ssc_export.csv
```

The new export can be a local path or a download URL (downloaded to
`data/ssc/`, encoding fixed automatically); with no argument the command
prompts for one. `--from-release` searches **all** releases of the repo
for the newest `mosty_*.db` asset (other database assets are ignored),
asks whether to update it, and only then prompts for the export;
`--yes` skips both questions.

The update shows a diff report first (new bridges, bridges gone, condition
changes) and asks for confirmation; `--yes` skips the prompt. Applying it
writes `data/mosty_{year}.db`: it overwrites current values, inserts new
bridges, archives bridges missing from the export (`archived`,
`archived_year` on `bridges` — they are kept, never deleted), refreshes
`locations`, and appends one `conditions` row per bridge for the new year.

Bridges that disappear and reappear under a new ID in the same year are
usually renumbered, not demolished — check the report before trusting the
archive list.

The downloaded release database is sanity-checked on fetch: it must be a
valid SQLite file with the current schema version and a readable source
year, and the update refuses to apply an export older than the base.

### The 2011 ID bridge

Exports up to 2011 have no `M####` bridge IDs. The history loader maps 2011
rows onto modern IDs using the 2012 export, which carries the old evidence
number (`evidenčné číslo - staré`) next to the new ID. Ambiguous matches are
skipped, not guessed; 2011 also needs value normalization (lowercase text,
`výborný` → `Bezchybný`, `neudaný` kept as `Neudaný`).

## Database schema

SQLite file with five tables:

| table | content |
|---|---|
| `bridges` | one row per bridge: name, road, year built, dimensions; `archived`/`archived_year` mark bridges that disappeared from a later export |
| `dcs` | dilatation units (*dilatačné celky*) — the bridge's children: material, construction type, load capacities, coordinates; FK to `bridges` |
| `locations` | bridge placement on road sections (úsek ID, nodes, staničenie); FK to `bridges` |
| `conditions` | history: one row per bridge and year — condition (*stavebno-technický stav*) and load capacities; FK to `bridges` |
| `metadata` | provenance: source file names, SHA-256 checksums, import dates, row counts, schema version |

Condition values on the 1–7 severity scale: `Bezchybný`, `Veľmi dobrý`,
`Dobrý`, `Uspokojivý`, `Zlý`, `Veľmi zlý`, `Havarijný` (code 7 = Havarijný).
Full schema documentation with query examples: [docs/database.md](docs/database.md).

Example — condition history of bridge M2717:

```sql
SELECT year, stavebno_technický_stav
FROM conditions
WHERE bridge_id = 'M2717'
ORDER BY year;
```

## Publishing

The repository ships code only. Databases are published as GitHub release
assets. The ground-zero release ships the asset `mosty.db`; updated releases
ship `mosty_{year}.db` under that exact name (`mosty_2026.db`,
`mosty_2027.db`, ...).

Provenance of every import lives in the `metadata` table (source file,
SHA-256, import date, row counts), so any released database testifies where
its data came from. `update --from-release` finds the newest `mosty_*.db`
across **all** releases and sanity-checks the download, so users running
the yearly update never need to track releases manually.
