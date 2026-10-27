"""Locale-aware parsing of individual cell values and per-column type inference."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DEFAULT_NULLS",
    "clean_cell",
    "parse_number",
    "parse_date",
    "decimal_evidence",
    "infer_column",
    "ColumnInfo",
]

DEFAULT_NULLS = frozenset(
    {
        "",
        "-",
        "--",
        "—",
        "–",
        "...",
        "..",
        "x",
        "na",
        "n/a",
        "nan",
        "null",
        "none",
        "nil",
        "#n/d",
        "#n/a",
        "#div/0!",
        "#valor!",
        "#value!",
        "#ref!",
        "#nome?",
        "#name?",
        "n/d",
        "s/d",
        "s.d.",
        "?",
    }
)
_TRUE = frozenset({"true", "verdadeiro", "sim", "s", "yes", "y"})
_FALSE = frozenset({"false", "falso", "não", "nao", "n", "no"})
_EXCEL_TEXT = re.compile(r'^="(.*)"$', re.S)
_CURRENCY = re.compile(r"^(?:R\$|US\$|\$|€|£|¥)\s*|\s*(?:R\$|€|£|¥)$")
_SPACE_GROUPS = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?")
_NUM = {
    ",": re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?|,\d+|\d+(?:,\d+)?[eE][+-]?\d+"),
    ".": re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+|\d+(?:\.\d+)?[eE][+-]?\d+"),
}
_DMY = re.compile(
    r"(\d{1,2})([/.-])(\d{1,2})\2(\d{4}|\d{2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,6}))?)?)?"
)
_YMD = re.compile(
    r"(\d{4})([/.-])(\d{1,2})\2(\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,6}))?)?)?(Z|[+-]\d{2}:?\d{2})?"
)


def clean_cell(raw: str) -> str:
    s = raw.strip().strip("\u00a0\u202f\ufeff")
    m = _EXCEL_TEXT.match(s)  # Excel's ="00123" trick to keep leading zeros
    return m.group(1) if m else s


def _strip_number(s: str) -> tuple[str, bool, bool]:
    """Remove sign, currency and percent. Returns (core, negative, percent)."""
    neg = False
    t = s.strip()
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    t = _CURRENCY.sub("", t).strip()
    if t[:1] in "-−":
        neg, t = not neg, t[1:].strip()
    elif t[:1] == "+":
        t = t[1:].strip()
    elif t.endswith("-"):  # SAP-style trailing minus: "1.234,00-"
        neg, t = not neg, t[:-1].strip()
    t = _CURRENCY.sub("", t).strip()
    pct = t.endswith("%")
    if pct:
        t = t[:-1].strip()
    if _SPACE_GROUPS.fullmatch(t):
        t = re.sub(r"[ \u00a0\u202f]", "", t)
    return t, neg, pct


def parse_number(s: str, decimal: str) -> tuple[int | float, bool, bool] | None:
    """Parse ``s`` with the given decimal separator.

    Returns ``(value, is_percent, has_fraction)`` or ``None``.
    """
    core, neg, pct = _strip_number(s)
    if not core or not _NUM[decimal].fullmatch(core):
        return None
    if decimal == ",":
        core = core.replace(".", "").replace(",", ".")
    else:
        core = core.replace(",", "")
    frac = "." in core or "e" in core.lower()
    value: int | float = float(core) if frac else int(core)
    return (-value if neg else value), pct, frac


_COMMA_ONLY = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+|\d+,(?:\d{1,2}|\d{4,})|0,\d+|\d{4,},\d{3}|\d{1,3}(?:\.\d{3}){2,}")
_POINT_ONLY = re.compile(r"\d{1,3}(?:,\d{3})+\.\d+|\d+\.(?:\d{1,2}|\d{4,})|0\.\d+|\d{4,}\.\d{3}|\d{1,3}(?:,\d{3}){2,}")


def decimal_evidence(cells: Iterable[str]) -> tuple[int, int]:
    """Count cells that can only be read with a comma (or point) as decimal separator."""
    comma = point = 0
    for s in cells:
        t = _strip_number(s)[0]
        if not t or not t[0].isdigit() and t[0] not in ".,":
            continue
        if _COMMA_ONLY.fullmatch(t):
            comma += 1
        elif _POINT_ONLY.fullmatch(t):
            point += 1
    return comma, point


def _year(y: str) -> int:
    n = int(y)
    if len(y) == 2:
        n += 2000 if n < 69 else 1900
    return n


def parse_date(s: str, dayfirst: bool) -> dt.date | dt.datetime | None:
    m = _YMD.fullmatch(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
        hh, mm, ss, frac, tz = m.group(5, 6, 7, 8, 9)
    else:
        m = _DMY.fullmatch(s)
        if not m:
            return None
        a, b, y = int(m.group(1)), int(m.group(3)), _year(m.group(4))
        d, mo = (a, b) if dayfirst else (b, a)
        hh, mm, ss, frac = m.group(5, 6, 7, 8)
        tz = None
    try:
        if hh is None:
            return dt.date(y, mo, d)
        micro = int((frac or "0").ljust(6, "0")[:6])
        value = dt.datetime(y, mo, d, int(hh), int(mm), int(ss or 0), micro)
        if tz:
            offset = dt.timezone.utc if tz == "Z" else dt.datetime.strptime(tz.replace(":", ""), "%z").tzinfo
            value = value.replace(tzinfo=offset)
        return value
    except ValueError:
        return None


def date_order_evidence(values: Iterable[str]) -> tuple[int, int]:
    """(# values proving day-first, # values proving month-first) for d/m/y-like strings."""
    day = month = 0
    for v in values:
        m = _DMY.fullmatch(v)
        if m:
            a, b = int(m.group(1)), int(m.group(3))
            day += a > 12 >= b
            month += b > 12 >= a
    return day, month


@dataclass
class ColumnInfo:
    name: str
    original_name: str
    type: str = "str"  # int | float | bool | date | datetime | str | empty
    nulls: int = 0
    percent: bool = False
    decimal: str | None = None
    dayfirst: bool | None = None
    examples: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def infer_column(
    values: Sequence[str],
    info: ColumnInfo,
    *,
    decimal: str,
    dayfirst: bool,
    nulls: frozenset[str],
) -> list[Any]:
    """Infer the type of a column, fill ``info`` and return the converted values."""
    cleaned = [clean_cell(v) for v in values]
    present = [(i, v) for i, v in enumerate(cleaned) if v.lower() not in nulls]
    info.nulls = len(cleaned) - len(present)
    info.examples = list(dict.fromkeys(v for _, v in present))[:3]
    out: list[Any] = [None] * len(cleaned)
    if not present:
        info.type = "empty"
        return out
    texts = [v for _, v in present]

    # booleans
    lowered = {v.lower() for v in texts}
    if lowered <= (_TRUE | _FALSE) and lowered & _TRUE and lowered & _FALSE:
        info.type = "bool"
        for i, v in present:
            out[i] = v.lower() in _TRUE
        return out

    # numbers (column-level decimal evidence wins over the file default)
    comma, point = decimal_evidence(texts)
    order = [","] if comma and not point else ["."] if point and not comma else [decimal]
    order += [d for d in (",", ".") if d not in order]
    for dec in order:
        parsed = [parse_number(v, dec) for v in texts]
        if all(p is not None for p in parsed):
            ints = [v for v in texts if not any(ch in v for ch in ".,eE%")]
            leading_zero = any(len(v) > 1 and v.lstrip("+-")[:1] == "0" for v in ints)
            huge = any(len(re.sub(r"\D", "", v)) >= 16 for v in ints)
            if leading_zero or huge:
                info.type = "str"
                info.warnings.append("kept as text (codes with leading zeros or very long identifiers)")
                for i, v in present:
                    out[i] = v
                return out
            has_frac = any(p[2] for p in parsed)
            info.percent = all(p[1] for p in parsed)
            info.type = "float" if has_frac or info.percent else "int"
            info.decimal = dec
            for (i, _), p in zip(present, parsed):
                out[i] = float(p[0]) if info.type == "float" else p[0]
            return out

    # dates
    day, month = date_order_evidence(texts)
    if not (day and month):
        first = True if day else False if month else dayfirst
        parsed_dates = [parse_date(v, first) for v in texts]
        if all(p is not None for p in parsed_dates):
            has_time = any(isinstance(p, dt.datetime) for p in parsed_dates)
            info.type = "datetime" if has_time else "date"
            info.dayfirst = first if any(_DMY.fullmatch(v) for v in texts) else None
            for (i, _), p in zip(present, parsed_dates):
                if has_time and not isinstance(p, dt.datetime):
                    p = dt.datetime(p.year, p.month, p.day)
                out[i] = p
            return out

    # text
    info.type = "str"
    numeric = sum(parse_number(v, order[0]) is not None for v in texts)
    if len(texts) >= 10 and numeric / len(texts) >= 0.9:
        bad = [v for v in texts if parse_number(v, order[0]) is None][:5]
        info.warnings.append(f"{numeric}/{len(texts)} values are numeric; kept as text because of {bad}")
    for i, v in present:
        out[i] = v
    return out
