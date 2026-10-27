"""Low-level detection: encoding, mojibake, delimiter and table boundaries."""

from __future__ import annotations

import codecs
import csv
import io
import math
import re
from collections import Counter

__all__ = [
    "detect_encoding",
    "fix_mojibake",
    "detect_delimiter",
    "parse_rows",
    "find_table",
]

_CP1252_HIGH = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
_CONT = f"[\u0080-\u00bf{_CP1252_HIGH}]"
# UTF-8 bytes that were wrongly decoded as Windows-1252/Latin-1 ("SÃ£o Paulo", "naÃ§Ã£o", "â€œ").
_MOJIBAKE = re.compile(f"[\u00c2-\u00df]{_CONT}|[\u00e0-\u00ef]{_CONT}{{2}}")
_FOOTER_START = re.compile(
    r"^\s*(?:fonte|source|nota|notas|note|notes|obs|observa[çc][ãa]o|elabora[çc][ãa]o|legenda|"
    r"sinais convencionais|\(\*|\*)",
    re.I,
)


def detect_encoding(raw: bytes) -> tuple[str, str]:
    """Guess the text encoding of ``raw``. Returns ``(encoding, reason)``."""
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", "BOM"
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16", "BOM"
    sample = raw[:4096]
    if sample and sample.count(0) > len(sample) * 0.25:
        odd_nuls = sample[1::2].count(0)
        even_nuls = sample[0::2].count(0)
        return ("utf-16-le" if odd_nuls > even_nuls else "utf-16-be"), "null bytes"
    try:
        raw.decode("utf-8")
        return "utf-8", "valid UTF-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("cp1252")
        return "cp1252", "not UTF-8; Windows-1252/Latin-1"
    except UnicodeDecodeError:
        return "latin-1", "not UTF-8"


def _repair(m: re.Match[str]) -> str:
    s = m.group()
    raw = bytearray()
    try:
        for ch in s:  # Windows-1252 for its special characters, Latin-1 for the rest
            raw += bytes([ord(ch)]) if ord(ch) < 256 else ch.encode("cp1252")
        return raw.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def fix_mojibake(text: str) -> tuple[str, int]:
    """Repair double-encoded UTF-8 sequences. Returns ``(text, n_repairs)``."""
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        fixed = _repair(m)
        if fixed != m.group():
            count += 1
        return fixed

    return _MOJIBAKE.sub(sub, text), count


def parse_rows(text: str, delimiter: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"'))


def _nonempty(row: list[str]) -> int:
    return sum(1 for c in row if c.strip())


def detect_delimiter(text: str, max_lines: int = 300) -> str:
    """Pick the delimiter that splits the sample into the most consistent table."""
    sample = "\n".join(text.splitlines()[:max_lines])
    digit_commas = len(re.findall(r"\d,\d", sample))
    commas = sample.count(",")
    best, best_score = ",", 0.0
    for d in (",", ";", "\t", "|"):
        if d not in sample:
            continue
        rows = [r for r in parse_rows(sample, d) if _nonempty(r)]
        widths = Counter(len(r) for r in rows if len(r) >= 2)
        if not widths:
            continue
        width, freq = max(widths.items(), key=lambda kv: (kv[1], kv[0]))
        score = freq / len(rows) * (1 + min(width, 30) / 30)
        if d == "," and commas and digit_commas / commas > 0.5:
            score *= 0.5  # commas are mostly decimal separators
        if score > best_score:
            best, best_score = d, score
    return best


_NUMERICISH = re.compile(r"^[\s(+\-−]*(?:R\$|US\$|\$|€|£)?\s*[\d.,\s]+%?\)?$")
_YEAR = re.compile(r"^(?:1[89]|2[01])\d{2}$")


def _looks_like_data(cell: str) -> bool:
    c = cell.strip()
    return bool(c) and bool(_NUMERICISH.match(c) or re.match(r"^\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}", c))


def find_table(rows: list[list[str]], header: bool | int | None = None) -> tuple[int, int, int, bool]:
    """Locate the table inside ``rows``.

    Returns ``(start, end, width, has_header)`` where ``rows[start:end]`` is the
    table (header included when ``has_header``).
    """
    widths = Counter(len(r) for r in rows if _nonempty(r) >= 2)
    if not widths:
        width = max((len(r) for r in rows), default=0)
    else:
        width = max(widths.items(), key=lambda kv: (kv[1], kv[0]))[0]

    # --- start: skip title lines / notes above the table
    if isinstance(header, int) and not isinstance(header, bool):
        start = header
    else:
        needed = max(2, math.ceil(width * 0.5)) if width >= 2 else 1
        start = next(
            (i for i, r in enumerate(rows) if _nonempty(r) >= needed and len(r) >= width - 1),
            0,
        )

    # --- end: drop footers ("Fonte: IBGE"), blank lines and short trailing rows
    end = len(rows)
    while end > start + 1:
        r = rows[end - 1]
        filled = [c for c in r if c.strip()]
        if not filled or _FOOTER_START.match(filled[0]):
            end -= 1
        elif width >= 3 and len(filled) <= 1 and len(r) < width / 2:
            end -= 1
        else:
            break

    # --- header or data?
    if isinstance(header, bool):
        has_header = header
    elif isinstance(header, int):
        has_header = True
    else:
        first = [c.strip() for c in rows[start]] if rows else []
        cells = [c for c in first if c]
        data_like = [c for c in cells if _looks_like_data(c)]
        years_only = data_like and all(_YEAR.match(c.replace(".", "")) for c in data_like)
        has_header = bool(cells) and (not data_like or bool(years_only))
    return start, end, width, has_header
