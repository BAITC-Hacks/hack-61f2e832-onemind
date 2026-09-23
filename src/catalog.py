"""Load and normalize the official contractor catalog."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import Contractor


REQUIRED_COLUMNS = {
    "id",
    "anon_name",
    "categories",
    "city",
    "city_imputed",
    "synthetic",
    "price_from_kzt",
    "price_imputed",
    "event_formats",
    "languages",
    "max_hours",
    "busy_dates",
    "description",
}


def _split_pipe(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    return tuple(part.strip() for part in value.split("|") if part.strip())


def _parse_bool(value: str, *, field: str, row_number: int) -> bool:
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"row {row_number}: {field} must be True or False")


def _parse_int(value: str, *, field: str, row_number: int) -> int:
    try:
        return int(value.strip())
    except ValueError as error:
        raise ValueError(f"row {row_number}: {field} must be an integer") from error


def _parse_max_hours(value: str, *, row_number: int) -> float | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError as error:
        raise ValueError(f"row {row_number}: max_hours must be numeric or blank") from error


def _parse_busy_dates(value: str, *, row_number: int) -> frozenset[date]:
    try:
        return frozenset(date.fromisoformat(item) for item in _split_pipe(value))
    except ValueError as error:
        raise ValueError(f"row {row_number}: busy_dates contains a non-ISO date") from error


def load_catalog(csv_path: str | Path) -> tuple[Contractor, ...]:
    """Read the official CSV without filling or changing any source values."""
    path = Path(csv_path)
    contractors: list[Contractor] = []

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = set(reader.fieldnames or ())
        missing_columns = REQUIRED_COLUMNS - columns
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"catalog is missing required columns: {missing}")

        for row_number, row in enumerate(reader, start=2):
            contractors.append(
                Contractor(
                    id=row["id"].strip(),
                    anon_name=row["anon_name"].strip(),
                    categories=_split_pipe(row["categories"]),
                    city=row["city"].strip(),
                    city_imputed=_parse_bool(
                        row["city_imputed"], field="city_imputed", row_number=row_number
                    ),
                    synthetic=_parse_bool(
                        row["synthetic"], field="synthetic", row_number=row_number
                    ),
                    price_from_kzt=_parse_int(
                        row["price_from_kzt"],
                        field="price_from_kzt",
                        row_number=row_number,
                    ),
                    price_imputed=_parse_bool(
                        row["price_imputed"],
                        field="price_imputed",
                        row_number=row_number,
                    ),
                    event_formats=_split_pipe(row["event_formats"]),
                    languages=_split_pipe(row["languages"]),
                    max_hours=_parse_max_hours(
                        row["max_hours"], row_number=row_number
                    ),
                    busy_dates=_parse_busy_dates(
                        row["busy_dates"], row_number=row_number
                    ),
                    description=row["description"].strip(),
                )
            )

    return tuple(contractors)
