# tidyread 🧹

[![CI](https://github.com/yagodejesus/tidyread/actions/workflows/ci.yml/badge.svg)](https://github.com/yagodejesus/tidyread/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/tidyread.svg)](https://pypi.org/project/tidyread/)
[![Python](https://img.shields.io/pypi/pyversions/tidyread.svg)](https://pypi.org/project/tidyread/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Read the messy CSVs that Excel and government portals produce — without guessing a single parameter.**

> 🇧🇷 *Leia os CSVs bagunçados de portais de dados abertos (IBGE, DATASUS, Receita, TSE…) e do Excel: detecta codificação, texto corrompido ("SÃ£o Paulo"), separador, vírgula decimal, datas dd/mm/aaaa, linhas de título e de rodapé ("Fonte: IBGE") — e devolve dados tipados.*

`pandas.read_csv` is great **once you know** the encoding, the delimiter, the decimal and thousands separators, the date format, how many title lines to skip, how many footer lines to drop and which strings mean "missing". `tidyread` figures all of that out for you, tells you what it found, and gives you clean, typed data.

```python
import tidyread

table = tidyread.read("municipios.csv", clean_names=True)
print(table.report())
df = table.to_pandas()      # proper Int64 / float / boolean / datetime dtypes
```

```text
tidyread report — examples/municipios_cp1252.csv
  encoding    cp1252 (not UTF-8; Windows-1252/Latin-1)
  delimiter   semicolon (';') · decimal ',' · thousands '.' · dates day-first (guessed)
  header      yes
  skipped     2 line(s) above the table: 'Tabela 1 - População residente e área territorial (dados fic'…
  skipped     2 footer line(s): 'Fonte: exemplo ilustrativo, números inventados.'…
  shape       5 rows × 6 columns
  columns
    municipio           str       e.g. 'Bragança', 'Augusto Corrêa'
    codigo_ibge         int       e.g. '1501709', '1500909'
    populacao           int       1 null · e.g. '130.122', '44.587'
    area_km2            float     e.g. '2.124,73', '1.099,22'
    densidade_hab_km2   float     1 null · e.g. '61,24', '40,56'
    data_de_referencia  date      e.g. '01/08/2022'
```

## Install

```bash
pip install tidyread            # zero dependencies
pip install "tidyread[pandas]"  # + to_pandas()
```

## What it handles

| Problem | Example | tidyread |
|---|---|---|
| Encoding | Windows-1252, Latin-1, UTF-8 with BOM, UTF-16 ("Unicode text" from Excel) | detected |
| Mojibake | `SÃ£o Paulo`, `â€œquotesâ€` (UTF-8 decoded twice) | repaired → `São Paulo` |
| Delimiter | `,` `;` tab `\|` — even when commas are also decimal separators | detected |
| Decimal / thousands | `1.234,56` vs `1,234.56`, `1 234,56`, decided **per column** | parsed |
| Currency, %, negatives | `R$ 1.234,56`, `12,5%`, `(1.000,00)`, `1.234,00-` | parsed |
| Dates | `31/12/2024`, `12/31/2024`, `2024-12-31T23:59:00Z`, `31.12.24 08:00` | `date` / `datetime`, order inferred from the data |
| Missing values | `-`, `...`, `X`, `NA`, `#N/D`, `#DIV/0!`, `null` | `None` |
| Title rows | `Tabela 1 - População residente…` above the header | skipped |
| Footers | `Fonte: IBGE`, `Notas: …`, `(*) …` | skipped |
| Codes | CEPs, `00123`, `="00123"` (Excel trick), 44-digit keys | kept as text (no lost zeros) |
| Booleans | `Sim/Não`, `S/N`, `true/false`, `yes/no` | `True` / `False` |
| Header quirks | missing, duplicated or empty names, years as headers (`2010;2022`) | handled |
| Excel padding | trailing `;;;;` and fully empty columns | dropped |

Every decision is visible in `table.detection` and in `table.report()`, and every one of them can be overridden.

## Usage

```python
import tidyread

t = tidyread.read("data.csv")               # path, bytes or binary file object
t = tidyread.read_text("a;b\n1,5;2\n")      # CSV already in a string

t.columns          # ['municipio', 'populacao', ...]
t.dtypes           # {'municipio': 'str', 'populacao': 'int', ...}
t.records()        # [{'municipio': 'Bragança', 'populacao': 130122, ...}, ...]
for row in t: ...  # one dict per row
t.column("populacao")

t.to_csv("clean.csv")    # UTF-8, comma-separated, '.' decimals, ISO dates
t.to_json("clean.json")
t.to_pandas()

t.detection.encoding, t.detection.delimiter, t.detection.decimal
t.detection.warnings     # e.g. "column 'valor': 19/20 values are numeric; kept as text because of ['erro']"
```

Override anything that the detection gets wrong:

```python
tidyread.read(
    "data.csv",
    encoding="latin-1",
    delimiter=";",
    decimal=",",
    dayfirst=True,
    header=3,                 # header is on row 3 (0-based); or True / False
    clean_names=True,         # "Área (km²)" → "area_km2"
    null_values={"", "-", "s/d"},
)
```

## Command line

```bash
tidyread messy.csv                         # just print the detection report
tidyread messy.csv -o clean.csv --clean-names
tidyread messy.csv -o clean.json
cat messy.csv | tidyread - -o - -q > clean.csv
```

## How it works

1. **Encoding** — BOMs first, then UTF-16 null-byte patterns, then strict UTF-8, then Windows-1252/Latin-1.
2. **Mojibake** — only byte sequences that are *valid UTF-8 read as Windows-1252* are repaired, so legitimate accents are never touched.
3. **Delimiter** — each candidate is scored by how consistent the column count is across rows; commas that sit between digits count against `,`.
4. **Table boundaries** — the header is the first row that fills at least half of the most common width; footers are trailing rows that start with *Fonte/Source/Notas/(\*)* or are almost empty.
5. **Types** — per column: booleans → numbers (with column-level decimal evidence such as `1.234,5` or `0,5`) → dates (day/month order proven by values like `31/12`) → text. Columns with leading zeros or 16+ digits stay text.

## Limitations

- Files are loaded into memory; for multi-GB files use the detection (`tidyread.read(open(f, "rb").read(5_000_000))`) to discover the parameters and pass them to a streaming reader.
- Multi-row headers (common in IBGE/SIDRA pivot tables) are read using the first header row only.
- When every value is ambiguous (`1.234` with no other evidence, or dates that never exceed 12), tidyread falls back to the file's convention and marks it as *guessed* in the report.

## Development

```bash
git clone https://github.com/yagodejesus/tidyread && cd tidyread
pip install -e ".[dev,pandas]"
pytest && ruff check .
```

Have a CSV that tidyread reads wrong? Please open an issue with a small anonymised sample — that is the best possible contribution.

## License

MIT © Yago de Jesus Martins
