# Database schema

The database is a SQLite file (see the [README](../README.md) for how it is
built and published). Entity model: a **bridge** (`bridges`) has children
**dilatation units** (`dcs`) — usually one, sometimes several. A bridge sits
on one or more **road sections** (`locations`). Every year's export appends a
**condition snapshot** per bridge (`conditions`). Import provenance lives in
`metadata`.

```
bridges 1──n dcs
bridges 1──n locations
bridges 1──n conditions
metadata (flat key-value)
```

## bridges

One row per bridge. Current values always reflect the newest applied export.

| column | type | content |
|---|---|---|
| `id_mosta` | TEXT PK | bridge ID, e.g. `M5897` |
| `trieda_pk` | TEXT | road class, e.g. `cesta I. triedy` |
| `číslo_pk` | TEXT | road number |
| `názov_mosta` | TEXT | bridge name/description |
| `správcovské_číslo` | TEXT | administration number (with leading zeros) |
| `rok_postavenia` | INTEGER | year built |
| `zaťažovacia_trieda_stn` | TEXT | load class per STN standard |
| `počet_otvorov` | INTEGER | number of spans |
| `dĺžka_premostenia` | REAL | bridged length [m] |
| `dĺžka_nosnej_konštrukcie` | REAL | load-bearing structure length [m] |
| `volná_šírka_mosta` | REAL | clear width [m] |
| `šírka_medzi_obrubami` | REAL | width between kerbs [m] |
| `plocha_mosta` | REAL | bridge area [m²] |
| `plocha_nosnej_konštrukcie` | REAL | load-bearing structure area [m²] |
| `okres` | TEXT | district |
| `archived` | INTEGER | `1` once the bridge disappears from an export |
| `archived_year` | INTEGER | year of the export it disappeared from |

## dcs

Dilatation units — the physically separate structures a bridge consists of.
Construction and load data live here, on the DC level.

| column | type | content |
|---|---|---|
| `id_dc` | TEXT PK | unit ID, e.g. `M5897.01` |
| `bridge_id` | TEXT FK | parent bridge |
| `stavebno_technický_stav` | TEXT | condition (see scale below) |
| `druh_konštrukcie` | TEXT | structure type, e.g. `dosková` |
| `material` | TEXT | material, e.g. `prefabrikovaný železobetón` |
| `normána_zaťažiteľnosť` | REAL | normal load capacity [t] |
| `výhradná_zaťažiteľnosť` | REAL | exceptional-but-permitted load [t] |
| `výnimočná_zaťažiteľnosť` | REAL | exceptional load [t] |
| `ojedinelá_zaťažiteľnosť` | REAL | single-case load [t] (since 2025) |
| `zaťažiteľnosť_na_nápravu` | REAL | load per axle [t] (since 2025) |
| `spôsob_stanovenia` | TEXT | how capacities were determined |
| `predmet_premostenia` | TEXT | what is bridged, e.g. `Vodný tok` |
| `longitude`, `latitude` | REAL | position (WGS-84) |
| `vyska` | REAL | altitude [m] |
| `správca_dc_mostu`, `vlastník_dc_mostu` | TEXT | administrator / owner |

## locations

Where the bridge meets the road network. One row per (bridge, section).

| column | type | content |
|---|---|---|
| `bridge_id` | TEXT FK+PK | parent bridge |
| `úsek_id` | TEXT PK | road section ID |
| `smer_úseku_pk`, `typ_úseku_pk` | TEXT | section direction / type |
| `počiatočný_uzol_úseku_pk`, `koncový_uzol_úseku_pk` | TEXT | section end nodes |
| `správca_úseku_pk`, `vlastník_úseku_pk` | TEXT | section administrator / owner |
| `úsekové_staničenie_začiatku_dc` | REAL | section stationing of DC start [m] |
| `kilometrovníkové_staničenie_začiatku_dc` | REAL | kilometre marker [km] |
| `kumulatívne_staničenie_začiatku_dc` | REAL | cumulative stationing [km] |
| `poradie` | INTEGER | section order |

## conditions

History — one row per bridge and year, appended by each import.

| column | type | content |
|---|---|---|
| `bridge_id` | TEXT FK+PK | parent bridge |
| `year` | INTEGER PK | export year |
| `stavebno_technický_stav` | TEXT | condition that year |
| `normána_zaťažiteľnosť` … `zaťažiteľnosť_na_nápravu` | REAL | load capacities that year |

Condition values form a 1–7 severity scale: `Bezchybný` (1), `Veľmi dobrý` (2),
`Dobrý` (3), `Uspokojivý` (4), `Zlý` (5), `Veľmi zlý` (6), `Havarijný` (7).
Pre-2012 exports additionally used `Výborný` (≈ Bezchybný) and `Neudaný`
(construction not yet handed over).

## metadata

Flat key-value provenance: `schema_version`, `source_file`, `source_sha256`,
`source_year`, `imported_at`, row counts, and per-year history imports
(`history_{year}_file`, `history_{year}_sha256`, ...).

## Query examples

Chronological condition history of one bridge:

```sql
SELECT year, stavebno_technický_stav, normána_zaťažiteľnost
FROM conditions
WHERE bridge_id = 'M2717'
ORDER BY year;
```

Bridges that deteriorated between two years (severity is the code order):

```sql
SELECT a.bridge_id, a.stavebno_technický_stav AS old, b.stavebno_technický_stav AS new
FROM conditions a
JOIN conditions b ON b.bridge_id = a.bridge_id AND b.year = 2025
WHERE a.year = 2021
  AND INSTR('Bezchybný|Veľmi dobrý|Dobrý|Uspokojivý|Zlý|Veľmi zlý|Havarijný',
            b.stavebno_technický_stav)
    > INSTR('Bezchybný|Veľmi dobrý|Dobrý|Uspokojivý|Zlý|Veľmi zlý|Havarijný',
            a.stavebno_technický_stav);
```

Condition distribution per year — how the fleet ages:

```sql
SELECT year, stavebno_technický_stav, COUNT(*) AS bridges
FROM conditions
GROUP BY year, stavebno_technický_stav
ORDER BY year, bridges DESC;
```

Latest known condition for every active bridge (joined with name and district):

```sql
SELECT b.id_mosta, b.názov_mosta, b.okres, c.year, c.stavebno_technický_stav
FROM bridges b
JOIN conditions c ON c.bridge_id = b.id_mosta
WHERE b.archived = 0
  AND c.year = (SELECT MAX(year) FROM conditions);
```

Full bridge card — properties, all units, all placements:

```sql
SELECT * FROM bridges WHERE id_mosta = 'M5897';

SELECT * FROM dcs WHERE bridge_id = 'M5897';

SELECT * FROM locations WHERE bridge_id = 'M5897' ORDER BY kumulatívne_staničenie_začiatku_dc;
```

Bridges with more than one dilatation unit:

```sql
SELECT b.id_mosta, b.názov_mosta, COUNT(*) AS dcs
FROM bridges b JOIN dcs d ON d.bridge_id = b.id_mosta
GROUP BY b.id_mosta
HAVING dcs > 1
ORDER BY dcs DESC;
```

Bridges archived in 2026 — candidates for demolition or renumbering review:

```sql
SELECT id_mosta, názov_mosta, rok_postavenia, archived_year
FROM bridges
WHERE archived = 1
ORDER BY archived_year, id_mosta;
```

All bridges on one road, with position along the road:

```sql
SELECT b.id_mosta, b.názov_mosta, l.kilometrovníkové_staničenie_začiatku_dc AS km
FROM bridges b
JOIN locations l ON l.bridge_id = b.id_mosta
WHERE b.trieda_pk = 'cesta I. triedy' AND b.číslo_pk = '2'
ORDER BY km;
```

Load-capacity drop for one bridge across history:

```sql
SELECT year, normána_zaťažiteľnost
FROM conditions
WHERE bridge_id = 'M2717' AND normána_zaťažiteľnost IS NOT NULL
ORDER BY year;
```
