# mosty

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
in order. Rebuild refuses to overwrite an existing database file.

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
uv run mosty init data/ssc/2025_ssc_export.csv --db data/mosty_2025.db
```

**3. Append condition history** from older exports (2011–2021 era):

```sh
uv run mosty history data/ssc/2017_ssc_export.csv --db data/mosty_2025.db
```

Each year loads once; loading an already-present year is refused. Years 2022+
use a different (Most/DC split) format and are handled by the yearly update
command, not the history loader. The 2010 export stays out on purpose: its
object IDs were renumbered by 2011, so less than 10% of bridges can be mapped —
not worth the noise.

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
| `bridges` | one row per bridge: name, road, year built, dimensions |
| `dcs` | dilatation units (*dilatačné celky*) — the bridge's children: material, construction type, load capacities, coordinates; FK to `bridges` |
| `locations` | bridge placement on road sections (úsek ID, nodes, staničenie); FK to `bridges` |
| `conditions` | history: one row per bridge and year — condition (*stavebno-technický stav*) and load capacities; FK to `bridges` |
| `metadata` | provenance: source file names, SHA-256 checksums, import dates, row counts, schema version |

Condition values on the 1–7 severity scale: `Bezchybný`, `Veľmi dobrý`,
`Dobrý`, `Uspokojivý`, `Zlý`, `Veľmi zlý`, `Havarijný` (code 7 = Havarijný).

Example — condition history of bridge M2717:

```sql
SELECT year, stavebno_technický_stav
FROM conditions
WHERE bridge_id = 'M2717'
ORDER BY year;
```

## Publishing

The repository ships code only. Databases are published as GitHub release
assets; the source CSVs must be downloaded from CDB. Provenance of every
import lives in the `metadata` table, so any released database testifies
where its data came from.
