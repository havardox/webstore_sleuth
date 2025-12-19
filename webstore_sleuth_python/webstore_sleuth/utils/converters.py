# Compiling regex globally is correct.
# Optimized to capture the widest possible numeric context.
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Optional

from dateutil.parser import isoparse
from dateutil.tz import UTC


_RE_NUMBER_CHUNK = re.compile(r"[\d\.,\-+]+")


def parse_price(value: Any) -> Decimal | None:
    if value is None:
        return None

    # 1. Handle native types
    if isinstance(value, Decimal):
        if value < 0:
            raise ValueError("Price cannot be negative")
        return value
    if isinstance(value, (int, float)):
        dec = Decimal(str(value))
        if dec < 0:
            raise ValueError("Price cannot be negative")
        return dec

    # 2. String cleanup
    s = str(value).strip()
    if not s:
        return None

    # Remove non-breaking spaces
    match = _RE_NUMBER_CHUNK.search(s.replace("\u00a0", ""))
    if not match:
        raise ValueError("Invalid price format")

    raw_num = match.group(0)

    # Counts to decide path
    dot_count = raw_num.count(".")
    comma_count = raw_num.count(",")

    clean_num = raw_num

    # ---------------------------------------------------------
    # Logic Branching
    # ---------------------------------------------------------
    if dot_count > 0 and comma_count > 0:
        # Case A: Mixed Separators (e.g., "1.200,50" or "1,200.50")
        # Rule: The last separator dictates the decimal split.
        if raw_num.rfind(".") > raw_num.rfind(","):
            clean_num = raw_num.replace(",", "")  # 1,200.50 -> 1200.50
        else:
            clean_num = raw_num.replace(".", "").replace(
                ",", "."
            )  # 1.200,50 -> 1200.50

    elif comma_count > 0 and dot_count == 0:
        # Case B: Only Commas
        # We split by the last comma to check the suffix length.
        parts = raw_num.rsplit(",", 1)
        suffix = parts[-1]

        # If 2 digits after comma -> Decimal (e.g. "19,99")
        # If >2 digits after comma -> Thousands (e.g. "1,000")

        # NOTE: I also include len < 2 (e.g. "12,5") as Decimal,
        # because "12,5" meaning "125" is extremely rare.
        if len(suffix) > 2:
            # Treated as Thousands Separator
            # "1,000" -> "1000"
            clean_num = raw_num.replace(",", "")
        else:
            # Treated as Decimal Separator
            # "12,99" -> "12.99"
            # "12,5"  -> "12.5"
            clean_num = raw_num.replace(",", ".")

    # (Case C: Only Dots. Python handles "12.99" natively, no action needed unless multiple dots)
    elif dot_count > 1:
        # "1.000.000" -> Remove dots
        clean_num = raw_num.replace(".", "")

    try:
        price = Decimal(clean_num)
    except InvalidOperation:
        raise ValueError(f"Invalid price format: {value}")

    if price < 0:
        raise ValueError("Price cannot be negative")

    return price


def parse_iso_date(s: str | None) -> datetime | None:
    """Parse ISO-like date strings using dateutil."""
    if not s:
        return None

    try:
        dt = isoparse(str(s))
    except (ValueError, TypeError):
        return None

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def ensure_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]
