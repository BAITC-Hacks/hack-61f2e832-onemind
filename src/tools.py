"""Minimal deterministic tools exposed to the recommendation agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Contractor, RecommendationQuery, RecommendationResult
from .recommender import ContractorRecommender


@dataclass(frozen=True)
class ContractorEvidence:
    contractor_id: str
    contractor_name: str
    categories: tuple[str, ...]
    city: str
    price_from_kzt: int
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: float | None
    busy_dates: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class RecommendationValidation:
    valid: bool
    expected_ids: tuple[str, ...]
    submitted_ids: tuple[str, ...]
    errors: tuple[str, ...]


class RecommendationTools:
    """Three small tools backed exclusively by the official catalog."""

    def __init__(self, catalog: Iterable[Contractor]) -> None:
        self._catalog = tuple(catalog)
        self._by_id = {contractor.id: contractor for contractor in self._catalog}
        if len(self._by_id) != len(self._catalog):
            raise ValueError("catalog contractor IDs must be unique")
        self._recommender = ContractorRecommender(self._catalog)

    def search_contractors(
        self, query: RecommendationQuery
    ) -> RecommendationResult:
        """Run the deterministic eligibility and ranking pipeline."""
        return self._recommender.recommend(query)

    def get_contractor_details(self, contractor_id: str) -> ContractorEvidence:
        """Return source evidence for one contractor without adding facts."""
        try:
            contractor = self._by_id[contractor_id]
        except KeyError as error:
            raise KeyError(f"unknown contractor ID: {contractor_id}") from error

        return ContractorEvidence(
            contractor_id=contractor.id,
            contractor_name=contractor.anon_name,
            categories=contractor.categories,
            city=contractor.city,
            price_from_kzt=contractor.price_from_kzt,
            event_formats=contractor.event_formats,
            languages=contractor.languages,
            max_hours=contractor.max_hours,
            busy_dates=tuple(sorted(day.isoformat() for day in contractor.busy_dates)),
            description=contractor.description,
        )

    def validate_recommendations(
        self,
        query: RecommendationQuery,
        contractor_ids: Iterable[str],
    ) -> RecommendationValidation:
        """Require exact deterministic IDs and ordering, with no additions."""
        submitted_ids = tuple(contractor_ids)
        expected_result = self.search_contractors(query)
        expected_ids = tuple(
            item.contractor.id for item in expected_result.recommendations
        )
        errors: list[str] = []

        if len(submitted_ids) > 3:
            errors.append("more than 3 contractor IDs were submitted")
        if len(set(submitted_ids)) != len(submitted_ids):
            errors.append("duplicate contractor IDs were submitted")
        unknown_ids = [item for item in submitted_ids if item not in self._by_id]
        if unknown_ids:
            errors.append(f"unknown contractor IDs: {', '.join(unknown_ids)}")
        if submitted_ids != expected_ids:
            errors.append("submitted IDs do not preserve deterministic selection and order")

        return RecommendationValidation(
            valid=not errors,
            expected_ids=expected_ids,
            submitted_ids=submitted_ids,
            errors=tuple(errors),
        )
