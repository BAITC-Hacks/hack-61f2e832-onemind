"""Explainable hard filtering and stable ranking."""

from __future__ import annotations

from fractions import Fraction
from typing import Callable, Iterable

from .models import (
    Contractor,
    RankedContractor,
    RecommendationDiagnostics,
    RecommendationQuery,
    RecommendationResult,
    ResultState,
)


def _normalized(value: str) -> str:
    return value.strip().casefold()


def _contains(values: Iterable[str], requested: str) -> bool:
    target = _normalized(requested)
    return any(_normalized(value) == target for value in values)


class ContractorRecommender:
    """Recommend up to three contractors from a preloaded official catalog."""

    def __init__(self, catalog: Iterable[Contractor]) -> None:
        self._catalog = tuple(catalog)

    def recommend(self, query: RecommendationQuery) -> RecommendationResult:
        city_candidates = [
            contractor
            for contractor in self._catalog
            if _normalized(contractor.city) == _normalized(query.city)
        ]
        category_candidates = [
            contractor
            for contractor in city_candidates
            if _contains(contractor.categories, query.contractor_category)
        ]

        stage_counts = {
            "after_city": len(city_candidates),
            "after_category": len(category_candidates),
        }
        rejected_counts = {
            "availability": 0,
            "event_format": 0,
            "budget": 0,
            "language": 0,
            "duration": 0,
        }
        available_categories = tuple(
            sorted(
                {category for item in city_candidates for category in item.categories},
                key=str.casefold,
            )
        )

        if not category_candidates:
            diagnostics = RecommendationDiagnostics(
                total_catalog=len(self._catalog),
                stage_counts=stage_counts,
                rejected_counts=rejected_counts,
                qualified_count=0,
                returned_count=0,
                available_categories=available_categories,
            )
            return RecommendationResult(
                state=ResultState.CATEGORY_NOT_FOUND,
                message=(
                    f"Category '{query.contractor_category}' does not exist in "
                    f"city '{query.city}'."
                ),
                recommendations=(),
                diagnostics=diagnostics,
            )

        candidates = category_candidates
        ordered_filters: tuple[
            tuple[str, Callable[[Contractor], bool]], ...
        ] = (
            (
                "availability",
                lambda contractor: query.event_date not in contractor.busy_dates,
            ),
            (
                "event_format",
                lambda contractor: _contains(
                    contractor.event_formats, query.event_format
                ),
            ),
            (
                "budget",
                lambda contractor: contractor.price_from_kzt <= query.budget_kzt,
            ),
            (
                "language",
                lambda contractor: query.language is None
                or _contains(contractor.languages, query.language),
            ),
            (
                "duration",
                lambda contractor: query.duration_hours is None
                or contractor.max_hours is None
                or contractor.max_hours >= query.duration_hours,
            ),
        )

        for filter_name, predicate in ordered_filters:
            passing: list[Contractor] = []
            for contractor in candidates:
                if predicate(contractor):
                    passing.append(contractor)
                else:
                    rejected_counts[filter_name] += 1
            candidates = passing
            stage_counts[f"after_{filter_name}"] = len(candidates)

        if not candidates:
            failure_summary = ", ".join(
                f"{reason}={count}"
                for reason, count in rejected_counts.items()
                if count
            )
            diagnostics = RecommendationDiagnostics(
                total_catalog=len(self._catalog),
                stage_counts=stage_counts,
                rejected_counts=rejected_counts,
                qualified_count=0,
                returned_count=0,
                available_categories=available_categories,
            )
            return RecommendationResult(
                state=ResultState.NO_MATCH,
                message=(
                    f"{len(category_candidates)} contractor(s) in '{query.city}' offer "
                    f"'{query.contractor_category}', but none passed all constraints. "
                    f"First-failure counts: {failure_summary}."
                ),
                recommendations=(),
                diagnostics=diagnostics,
            )

        ranked = sorted(
            (self._rank(contractor, query) for contractor in candidates),
            key=lambda item: (
                -item[0],
                item[1].price_from_kzt,
                _normalized(item[1].anon_name),
                item[1].id,
            ),
        )
        recommendations = tuple(
            RankedContractor(
                contractor=contractor,
                score=round(float(score), 6),
                score_components={
                    name: round(float(value), 6)
                    for name, value in components.items()
                },
            )
            for score, contractor, components in ranked[:3]
        )

        qualified_count = len(candidates)
        if qualified_count < 3:
            message = (
                f"Only {qualified_count} contractor(s) passed all constraints, so fewer "
                "than 3 are returned."
            )
        elif qualified_count > 3:
            message = (
                f"Found {qualified_count} qualifying contractors; returning the top 3 "
                "by deterministic rank."
            )
        else:
            message = "Found and returned 3 qualifying contractors."

        diagnostics = RecommendationDiagnostics(
            total_catalog=len(self._catalog),
            stage_counts=stage_counts,
            rejected_counts=rejected_counts,
            qualified_count=qualified_count,
            returned_count=len(recommendations),
            available_categories=available_categories,
        )
        return RecommendationResult(
            state=ResultState.MATCHED,
            message=message,
            recommendations=recommendations,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _rank(
        contractor: Contractor, query: RecommendationQuery
    ) -> tuple[Fraction, Contractor, dict[str, Fraction]]:
        """Score real evidence only, on a 100-point scale.

        Budget headroom contributes up to 70 points. A requested and supported
        language contributes 15. When duration is requested and capacity is
        known, a closer sufficient fit contributes up to 15; unknown capacity
        remains eligible but receives no duration evidence points. Fraction
        arithmetic and explicit tie-breakers make ordering reproducible.
        """
        budget_score = (
            Fraction(query.budget_kzt - contractor.price_from_kzt, query.budget_kzt)
            * 70
            if query.budget_kzt
            else Fraction(0)
        )
        language_score = Fraction(15) if query.language is not None else Fraction(0)
        duration_score = Fraction(0)
        if query.duration_hours is not None and contractor.max_hours is not None:
            duration_score = (
                Fraction(str(query.duration_hours))
                / Fraction(str(contractor.max_hours))
                * 15
            )

        components = {
            "budget_headroom": budget_score,
            "language_match": language_score,
            "duration_fit": duration_score,
        }
        return sum(components.values(), Fraction(0)), contractor, components
