"""Typed contracts shared by the catalog loader and recommender."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ResultState(str, Enum):
    MATCHED = "MATCHED"
    CATEGORY_NOT_FOUND = "CATEGORY_NOT_FOUND"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True)
class Contractor:
    id: str
    anon_name: str
    categories: tuple[str, ...]
    city: str
    city_imputed: bool
    synthetic: bool
    price_from_kzt: int
    price_imputed: bool
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: float | None
    busy_dates: frozenset[date]
    description: str


@dataclass(frozen=True)
class RecommendationQuery:
    city: str
    event_date: date
    event_format: str
    contractor_category: str
    budget_kzt: int
    duration_hours: float | None = None
    language: str | None = None

    @classmethod
    def from_values(
        cls,
        *,
        city: str,
        event_date: str | date,
        event_format: str,
        contractor_category: str,
        budget_kzt: int,
        duration_hours: float | None = None,
        language: str | None = None,
    ) -> "RecommendationQuery":
        """Validate and normalize values supplied by a future UI or agent."""
        normalized_date = (
            date.fromisoformat(event_date.strip())
            if isinstance(event_date, str)
            else event_date
        )
        if not isinstance(normalized_date, date):
            raise TypeError("event_date must be an ISO date string or date")

        required_strings = {
            "city": city.strip(),
            "event_format": event_format.strip(),
            "contractor_category": contractor_category.strip(),
        }
        for field_name, value in required_strings.items():
            if not value:
                raise ValueError(f"{field_name} must not be blank")
        if isinstance(budget_kzt, bool) or not isinstance(budget_kzt, int):
            raise TypeError("budget_kzt must be an integer")
        if budget_kzt < 0:
            raise ValueError("budget_kzt must be non-negative")
        if duration_hours is not None:
            if isinstance(duration_hours, bool) or not isinstance(
                duration_hours, (int, float)
            ):
                raise TypeError("duration_hours must be a number")
            if duration_hours <= 0:
                raise ValueError("duration_hours must be greater than zero")

        normalized_language = language.strip() if language is not None else None
        if normalized_language == "":
            normalized_language = None

        return cls(
            city=required_strings["city"],
            event_date=normalized_date,
            event_format=required_strings["event_format"],
            contractor_category=required_strings["contractor_category"],
            budget_kzt=budget_kzt,
            duration_hours=float(duration_hours) if duration_hours is not None else None,
            language=normalized_language,
        )


@dataclass(frozen=True)
class RankedContractor:
    contractor: Contractor
    score: float
    score_components: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "score_components", MappingProxyType(dict(self.score_components))
        )


@dataclass(frozen=True)
class RecommendationDiagnostics:
    total_catalog: int
    stage_counts: Mapping[str, int]
    rejected_counts: Mapping[str, int]
    qualified_count: int
    returned_count: int
    available_categories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_counts", MappingProxyType(dict(self.stage_counts)))
        object.__setattr__(
            self, "rejected_counts", MappingProxyType(dict(self.rejected_counts))
        )


@dataclass(frozen=True)
class RecommendationResult:
    state: ResultState
    message: str
    recommendations: tuple[RankedContractor, ...]
    diagnostics: RecommendationDiagnostics
