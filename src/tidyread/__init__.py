"""tidyread — read the messy CSVs that Excel and government portals produce."""

__version__ = "0.1.0"

from .detect import detect_delimiter, detect_encoding, fix_mojibake
from .table import Detection, Table, clean_name, read, read_text
from .values import ColumnInfo

__all__ = [
    "__version__",
    "ColumnInfo",
    "Detection",
    "Table",
    "clean_name",
    "detect_delimiter",
    "detect_encoding",
    "fix_mojibake",
    "read",
    "read_text",
]
