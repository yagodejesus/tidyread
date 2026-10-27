"""Command line: ``tidyread messy.csv -o clean.csv``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .table import read

_DELIMS = {"comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tidyread",
        description="Read a messy CSV (any encoding, delimiter, decimal style or date format) "
        "and write a clean UTF-8 CSV or JSON.",
    )
    p.add_argument("file", help="input CSV ('-' for stdin)")
    p.add_argument("-o", "--output", help="output file (.csv or .json); '-' for stdout")
    p.add_argument("--json", action="store_true", help="write JSON instead of CSV")
    p.add_argument("--clean-names", action="store_true", help="snake_case ASCII column names")
    p.add_argument("--encoding")
    p.add_argument("--delimiter", help="',', ';', 'tab', 'pipe' …")
    p.add_argument("--decimal", choices=(",", "."))
    order = p.add_mutually_exclusive_group()
    order.add_argument("--dayfirst", action="store_true", default=None)
    order.add_argument("--monthfirst", dest="dayfirst", action="store_false")
    p.add_argument("--no-header", action="store_true", help="the file has no header row")
    p.add_argument("-q", "--quiet", action="store_true", help="don't print the detection report")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = p.parse_args(argv)

    source = sys.stdin.buffer if a.file == "-" else a.file
    delimiter = _DELIMS.get(a.delimiter, a.delimiter) if a.delimiter else None
    table = read(
        source,
        encoding=a.encoding,
        delimiter=delimiter,
        decimal=a.decimal,
        dayfirst=a.dayfirst,
        header=False if a.no_header else None,
        clean_names=a.clean_names,
    )
    if not a.quiet:
        print(table.report(), file=sys.stderr)
    if a.output:
        as_json = a.json or a.output.lower().endswith(".json")
        if a.output == "-":
            sys.stdout.write(table.to_json() + "\n" if as_json else table.to_csv())
        elif as_json:
            table.to_json(a.output)
        else:
            table.to_csv(a.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
