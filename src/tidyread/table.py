"""High-level API: :func:`read` and :class:`Table`."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from .detect import detect_delimiter, detect_encoding, find_table, fix_mojibake, parse_rows
from .values import DEFAULT_NULLS, ColumnInfo, date_order_evidence, decimal_evidence, infer_column

__all__ = ["read", "read_text", "Table", "Detection", "clean_name"]

_DELIM_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}


def clean_name(name: str) -> str:
    """``"Valor (R$) – 2024"`` → ``"valor_r_2024"``."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return s


@dataclass
class Detection:
    """Everything tidyread figured out about the file."""

    encoding: str
    encoding_reason: str
    mojibake_fixes: int
    delimiter: str
    decimal: str
    dayfirst: bool
    dayfirst_guessed: bool
    header: bool
    skipped_top: list[str] = field(default_factory=list)
    skipped_bottom: list[str] = field(default_factory=list)
    ragged_rows: int = 0
    dropped_empty_columns: int = 0
    columns: list[ColumnInfo] = field(default_factory=list)

    @property
    def thousands(self) -> str:
        return "." if self.decimal == "," else ","

    @property
    def warnings(self) -> list[str]:
        w = [f"column {c.name!r}: {msg}" for c in self.columns for msg in c.warnings]
        if self.ragged_rows:
            w.append(f"{self.ragged_rows} row(s) had extra non-empty cells beyond the header width")
        return w


class Table:
    """A typed, cleaned table. Iterate over it to get one ``dict`` per row."""

    def __init__(self, columns: list[str], rows: list[list[Any]], detection: Detection, source: str = ""):
        self.columns = columns
        self.rows = rows
        self.detection = detection
        self.source = source

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for r in self.rows:
            yield dict(zip(self.columns, r))

    def __repr__(self) -> str:
        return f"<Table {len(self.rows)} rows × {len(self.columns)} columns from {self.source or 'data'}>"

    @property
    def dtypes(self) -> dict[str, str]:
        return {c.name: c.type for c in self.detection.columns}

    def column(self, name: str) -> list[Any]:
        i = self.columns.index(name)
        return [r[i] for r in self.rows]

    def records(self) -> list[dict[str, Any]]:
        return list(self)

    # ------------------------------------------------------------------ export
    @staticmethod
    def _fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (dt.date, dt.datetime)):
            return v.isoformat()
        return str(v)

    def to_csv(self, path: str | os.PathLike[str] | None = None, delimiter: str = ",") -> str | None:
        """Write a clean UTF-8 CSV (ISO dates, ``.`` as decimal). Returns the text if no path."""
        buf = io.StringIO(newline="")
        w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
        w.writerow(self.columns)
        w.writerows([self._fmt(v) for v in r] for r in self.rows)
        if path is None:
            return buf.getvalue()
        Path(path).write_text(buf.getvalue(), encoding="utf-8", newline="")
        return None

    def to_json(self, path: str | os.PathLike[str] | None = None, indent: int | None = 2) -> str | None:
        data = [{k: (self._fmt(v) if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in r.items()} for r in self]
        text = json.dumps(data, ensure_ascii=False, indent=indent)
        if path is None:
            return text
        Path(path).write_text(text, encoding="utf-8")
        return None

    def to_pandas(self):  # noqa: ANN201 - pandas is optional
        """Convert to a :class:`pandas.DataFrame` with proper (nullable) dtypes."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise ImportError("to_pandas() requires pandas: pip install 'tidyread[pandas]'") from exc
        data: dict[str, Any] = {}
        for i, info in enumerate(self.detection.columns):
            col = [r[i] for r in self.rows]
            if info.type == "int":
                data[info.name] = pd.array(col, dtype="Int64")
            elif info.type == "float":
                data[info.name] = pd.array([float("nan") if v is None else v for v in col], dtype="float64")
            elif info.type == "bool":
                data[info.name] = pd.array(col, dtype="boolean")
            elif info.type in ("date", "datetime"):
                data[info.name] = pd.to_datetime(pd.Series(col, dtype="object"))
            else:
                data[info.name] = pd.Series(col, dtype="object")
        return pd.DataFrame(data, columns=self.columns)

    # ------------------------------------------------------------------ report
    def report(self) -> str:
        d = self.detection
        enc = f"{d.encoding} ({d.encoding_reason})"
        if d.mojibake_fixes:
            enc += f" · repaired {d.mojibake_fixes} garbled character sequence(s)"
        order = "day-first" + (" (guessed)" if d.dayfirst_guessed else "")
        if not d.dayfirst:
            order = "month-first" + (" (guessed)" if d.dayfirst_guessed else "")
        lines = [
            f"tidyread report — {self.source or 'data'}",
            f"  encoding    {enc}",
            f"  delimiter   {_DELIM_NAMES.get(d.delimiter, repr(d.delimiter))} ({d.delimiter!r})"
            f" · decimal {d.decimal!r} · thousands {d.thousands!r} · dates {order}",
            f"  header      {'yes' if d.header else 'no (generated column names)'}",
        ]
        if d.skipped_top:
            lines.append(f"  skipped     {len(d.skipped_top)} line(s) above the table: {d.skipped_top[0][:60]!r}…")
        if d.skipped_bottom:
            lines.append(f"  skipped     {len(d.skipped_bottom)} footer line(s): {d.skipped_bottom[0][:60]!r}…")
        if d.dropped_empty_columns:
            lines.append(f"  dropped     {d.dropped_empty_columns} empty column(s)")
        lines.append(f"  shape       {len(self.rows):,} rows × {len(self.columns)} columns")
        lines.append("  columns")
        width = max((len(c.name) for c in d.columns), default=4)
        for c in d.columns:
            extra = []
            if c.percent:
                extra.append("percent")
            if c.nulls:
                extra.append(f"{c.nulls} null")
            if c.examples:
                extra.append("e.g. " + ", ".join(repr(e) for e in c.examples[:2]))
            lines.append(f"    {c.name:<{width}}  {c.type:<8}  {' · '.join(extra)}")
        for w in d.warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


def _load(source: str | os.PathLike[str] | bytes | IO[Any]) -> tuple[bytes | str, str]:
    if isinstance(source, bytes):
        return source, "bytes"
    if isinstance(source, (str, os.PathLike)):
        return Path(source).read_bytes(), str(source)
    data = source.read()
    return data, getattr(source, "name", "stream")


def read(
    source: str | os.PathLike[str] | bytes | IO[Any],
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    decimal: str | None = None,
    dayfirst: bool | None = None,
    header: bool | int | None = None,
    clean_names: bool = False,
    null_values: Iterable[str] | None = None,
    repair_mojibake: bool = True,
    drop_empty_columns: bool = True,
) -> Table:
    """Read a messy CSV into a typed :class:`Table`.

    Every argument left as ``None`` is detected automatically:

    - ``encoding``: UTF-8 (with/without BOM), UTF-16, Windows-1252 or Latin-1;
    - ``delimiter``: ``,`` ``;`` tab or ``|``;
    - ``decimal``: ``","`` (``1.234,56``) or ``"."`` (``1,234.56``);
    - ``dayfirst``: ``31/12/2024`` vs ``12/31/2024``;
    - ``header``: row index of the header, ``True``/``False``, or auto.
    """
    raw, name = _load(source)
    if isinstance(raw, str):
        text, enc, reason = raw, "text", "already decoded"
    else:
        enc, reason = (encoding, "given") if encoding else detect_encoding(raw)
        text = raw.decode(enc, errors="replace")
    text = text.lstrip("\ufeff")
    fixes = 0
    if repair_mojibake:
        text, fixes = fix_mojibake(text)
    return _from_text(
        text,
        name,
        Detection(enc, reason, fixes, "", "", True, False, False),
        delimiter=delimiter,
        decimal=decimal,
        dayfirst=dayfirst,
        header=header,
        clean_names=clean_names,
        null_values=null_values,
        drop_empty_columns=drop_empty_columns,
    )


def read_text(text: str, **kwargs: Any) -> Table:
    """Like :func:`read`, for CSV content that is already a ``str``."""
    return read(io.StringIO(text), **kwargs)


def _from_text(
    text: str,
    name: str,
    det: Detection,
    *,
    delimiter: str | None,
    decimal: str | None,
    dayfirst: bool | None,
    header: bool | int | None,
    clean_names: bool,
    null_values: Iterable[str] | None,
    drop_empty_columns: bool,
) -> Table:
    det.delimiter = delimiter or detect_delimiter(text)
    rows = parse_rows(text, det.delimiter)
    start, end, width, has_header = find_table(rows, header)
    det.header = has_header
    det.skipped_top = [
        det.delimiter.join(r).strip(det.delimiter + " ") for r in rows[:start] if any(c.strip() for c in r)
    ]
    det.skipped_bottom = [
        det.delimiter.join(r).strip(det.delimiter + " ") for r in rows[end:] if any(c.strip() for c in r)
    ]

    table_rows = rows[start:end]
    head = table_rows[0] if has_header and table_rows else []
    body = table_rows[1:] if has_header else table_rows
    width = max(width, len(head))

    data: list[list[str]] = []
    for r in body:
        if not any(c.strip() for c in r):
            continue
        if len(r) > width:
            if any(c.strip() for c in r[width:]):
                det.ragged_rows += 1
            r = r[:width]
        data.append(r + [""] * (width - len(r)))

    names = [h.strip() for h in head] + [""] * (width - len(head))
    names = [n or f"column_{i + 1}" for i, n in enumerate(names)]
    originals = list(names)
    if clean_names:
        names = [clean_name(n) or f"column_{i + 1}" for i, n in enumerate(names)]
    seen: dict[str, int] = {}
    for i, n in enumerate(names):
        if n in seen:
            seen[n] += 1
            names[i] = f"{n}_{seen[n]}"
        else:
            seen[n] = 1

    nulls = frozenset(v.lower() for v in null_values) if null_values is not None else DEFAULT_NULLS
    columns = [[r[i] for r in data] for i in range(width)]
    sample_cells = [c for col in columns for c in col[:500]]

    if decimal:
        det.decimal = decimal
    else:
        comma, point = decimal_evidence(sample_cells)
        det.decimal = "," if comma > point else "." if point > comma else ("," if det.delimiter == ";" else ".")
    if dayfirst is not None:
        det.dayfirst, det.dayfirst_guessed = dayfirst, False
    else:
        day, month = date_order_evidence(c.strip() for c in sample_cells)
        if day or month:
            det.dayfirst, det.dayfirst_guessed = day >= month, False
        else:
            det.dayfirst, det.dayfirst_guessed = det.decimal == ",", True

    converted: list[list[Any]] = []
    infos: list[ColumnInfo] = []
    for i in range(width):
        info = ColumnInfo(names[i], originals[i])
        converted.append(infer_column(columns[i], info, decimal=det.decimal, dayfirst=det.dayfirst, nulls=nulls))
        infos.append(info)

    keep = [
        i
        for i, info in enumerate(infos)
        if not (drop_empty_columns and info.type == "empty" and originals[i].startswith("column_"))
    ]
    det.dropped_empty_columns = width - len(keep)
    det.columns = [infos[i] for i in keep]
    out_rows = [[converted[i][j] for i in keep] for j in range(len(data))]
    return Table([names[i] for i in keep], out_rows, det, name)
