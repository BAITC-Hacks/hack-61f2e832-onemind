"""Single-orchestrator AI layer for grounded contractor explanations."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Protocol

from .models import (
    RecommendationDiagnostics,
    RecommendationQuery,
    RecommendationResult,
    ResultState,
)
from .tools import ContractorEvidence, RecommendationTools


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExplanationItem:
    contractor_id: str
    explanation: str


@dataclass(frozen=True)
class ExplanationDraft:
    summary: str
    explanations: tuple[ExplanationItem, ...]


@dataclass(frozen=True)
class ContractorCard:
    contractor_id: str
    contractor_name: str
    category: str
    city: str
    price_kzt: int
    explanation: str


@dataclass(frozen=True)
class AgentRecommendationResponse:
    state: ResultState
    message: str
    cards: tuple[ContractorCard, ...]
    diagnostics: RecommendationDiagnostics
    explanation_mode: str


class ExplanationProvider(Protocol):
    mode: str

    def generate(
        self,
        query: RecommendationQuery,
        result: RecommendationResult,
        evidence: tuple[ContractorEvidence, ...],
    ) -> ExplanationDraft: ...


class OpenAIExplanationProvider:
    """One minimal Responses API call that cannot control recommendation IDs."""

    mode = "openai"

    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        if not api_key:
            raise ValueError("api_key must not be blank")
        self._api_key = api_key
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @classmethod
    def from_environment(cls) -> "OpenAIExplanationProvider | None":
        api_key = os.getenv("OPENAI_API_KEY")
        return cls(api_key=api_key) if api_key else None

    def generate(
        self,
        query: RecommendationQuery,
        result: RecommendationResult,
        evidence: tuple[ContractorEvidence, ...],
    ) -> ExplanationDraft:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("the openai package is not installed") from error

        client = OpenAI(
            api_key=self._api_key,
            timeout=8.0,
            max_retries=0,
        )
        response = client.responses.create(
            model=self._model,
            instructions=(
                "You write concise contractor recommendation explanations. Use only "
                "the supplied query, deterministic result, and contractor evidence. "
                "Never add ratings, capabilities, availability, languages, prices, "
                "experience, or services not present in the evidence. Return the "
                "summary exactly as supplied. For MATCHED results, return exactly one "
                "1-2 sentence explanation per supplied contractor, preserving IDs and "
                "order. Write every explanation entirely in natural Russian. In every "
                "explanation, include the contractor's exact numeric price_from_kzt, "
                "formatted naturally with digit grouping, and the exact requested "
                "event_format text as supplied. Do not translate Russian evidence "
                "markers into English. Also differentiate candidates with concrete "
                "description evidence. Keep each explanation to 1-2 sentences. "
                "For empty results, return no contractor explanations."
            ),
            input=json.dumps(
                {
                    "query": _query_payload(query),
                    "state": result.state.value,
                    "summary_to_copy_exactly": result.message,
                    "diagnostics": {
                        "stage_counts": dict(result.diagnostics.stage_counts),
                        "rejected_counts": dict(result.diagnostics.rejected_counts),
                    },
                    "contractors": [
                        _evidence_payload(query, item) for item in evidence
                    ],
                },
                ensure_ascii=False,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "contractor_explanations",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "explanations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "contractor_id": {"type": "string"},
                                        "explanation": {"type": "string"},
                                    },
                                    "required": ["contractor_id", "explanation"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["summary", "explanations"],
                        "additionalProperties": False,
                    },
                }
            },
            temperature=0,
            max_output_tokens=700,
            store=False,
        )
        payload = json.loads(response.output_text)
        return ExplanationDraft(
            summary=payload["summary"],
            explanations=tuple(
                ExplanationItem(
                    contractor_id=item["contractor_id"],
                    explanation=item["explanation"].strip(),
                )
                for item in payload["explanations"]
            ),
        )


class RecommendationAgent:
    """Orchestrate deterministic tools, explanation generation, and validation."""

    def __init__(
        self,
        tools: RecommendationTools,
        explanation_provider: ExplanationProvider | None = None,
    ) -> None:
        self._tools = tools
        self._provider = (
            explanation_provider
            if explanation_provider is not None
            else OpenAIExplanationProvider.from_environment()
        )

    def recommend(self, query: RecommendationQuery) -> AgentRecommendationResponse:
        deterministic_result = self._tools.search_contractors(query)
        evidence = tuple(
            self._tools.get_contractor_details(item.contractor.id)
            for item in deterministic_result.recommendations
        )
        draft = _fallback_draft(query, deterministic_result, evidence)
        explanation_mode = "deterministic_fallback"

        if self._provider is not None:
            try:
                generated = self._provider.generate(
                    query, deterministic_result, evidence
                )
                if _valid_draft(generated, query, deterministic_result, evidence):
                    draft = generated
                    explanation_mode = self._provider.mode
            except Exception as error:
                # API, schema, refusal, and timeout failures all preserve a demoable MVP.
                logger.warning(
                    "OpenAI explanation failed; using deterministic fallback (%s: %s)",
                    type(error).__name__,
                    error,
                )

        submitted_ids = tuple(item.contractor_id for item in draft.explanations)
        validation = self._tools.validate_recommendations(query, submitted_ids)
        if not validation.valid:
            draft = _fallback_draft(query, deterministic_result, evidence)
            explanation_mode = "deterministic_fallback"
            submitted_ids = tuple(item.contractor_id for item in draft.explanations)
            validation = self._tools.validate_recommendations(query, submitted_ids)
        if not validation.valid:
            raise RuntimeError("deterministic recommendation validation failed")

        explanation_by_id = {
            item.contractor_id: item.explanation for item in draft.explanations
        }
        cards = tuple(
            ContractorCard(
                contractor_id=item.contractor.id,
                contractor_name=item.contractor.anon_name,
                category=query.contractor_category,
                city=item.contractor.city,
                price_kzt=item.contractor.price_from_kzt,
                explanation=explanation_by_id[item.contractor.id],
            )
            for item in deterministic_result.recommendations
        )
        return AgentRecommendationResponse(
            state=deterministic_result.state,
            message=draft.summary,
            cards=cards,
            diagnostics=deterministic_result.diagnostics,
            explanation_mode=explanation_mode,
        )


def _query_payload(query: RecommendationQuery) -> dict[str, object]:
    return {
        "city": query.city,
        "event_date": query.event_date.isoformat(),
        "event_format": query.event_format,
        "contractor_category": query.contractor_category,
        "budget_kzt": query.budget_kzt,
        "duration_hours": query.duration_hours,
        "language": query.language,
    }


def _evidence_payload(
    query: RecommendationQuery, evidence: ContractorEvidence
) -> dict[str, object]:
    """Send only useful evidence to the model, not the full busy-date calendar."""
    return {
        "contractor_id": evidence.contractor_id,
        "contractor_name": evidence.contractor_name,
        "categories": evidence.categories,
        "city": evidence.city,
        "price_from_kzt": evidence.price_from_kzt,
        "event_formats": evidence.event_formats,
        "languages": evidence.languages,
        "max_hours": evidence.max_hours,
        "available_on_event_date": query.event_date.isoformat()
        not in evidence.busy_dates,
        "description": evidence.description,
    }


def _valid_draft(
    draft: ExplanationDraft,
    query: RecommendationQuery,
    result: RecommendationResult,
    evidence: tuple[ContractorEvidence, ...],
) -> bool:
    expected_ids = tuple(item.contractor.id for item in result.recommendations)
    submitted_ids = tuple(item.contractor_id for item in draft.explanations)
    if draft.summary != result.message or submitted_ids != expected_ids:
        return False
    return all(
        item.explanation.strip()
        and _contains_concrete_evidence(item.explanation, query, contractor)
        for item, contractor in zip(draft.explanations, evidence)
    )


def _contains_concrete_evidence(
    explanation: str,
    query: RecommendationQuery,
    evidence: ContractorEvidence,
) -> bool:
    normalized = explanation.casefold().replace(" ", "").replace(",", "")
    markers = {
        str(evidence.price_from_kzt),
        query.event_date.isoformat().casefold(),
        query.event_format.casefold().replace(" ", ""),
    }
    if query.language is not None:
        markers.add(query.language.casefold().replace(" ", ""))
    if query.duration_hours is not None:
        markers.add(f"{query.duration_hours:g}")
    if evidence.max_hours is not None:
        markers.add(f"{evidence.max_hours:g}")
    return any(marker in normalized for marker in markers)


def _fallback_draft(
    query: RecommendationQuery,
    result: RecommendationResult,
    evidence: tuple[ContractorEvidence, ...],
) -> ExplanationDraft:
    explanations = tuple(
        ExplanationItem(
            contractor_id=item.contractor_id,
            explanation=_fallback_explanation(query, item),
        )
        for item in evidence
    )
    return ExplanationDraft(summary=result.message, explanations=explanations)


def _fallback_explanation(
    query: RecommendationQuery, evidence: ContractorEvidence
) -> str:
    price = f"{evidence.price_from_kzt:,}".replace(",", " ")
    budget = f"{query.budget_kzt:,}".replace(",", " ")
    first_sentence = (
        f"Стоимость услуг {evidence.contractor_name} — от {price} ₸, что укладывается "
        f"в бюджет {budget} ₸; подрядчик работает с форматом «{query.event_format}» "
        f"и свободен {query.event_date.isoformat()}."
    )
    details: list[str] = []
    if query.language is not None:
        details.append(f"работает на языке «{query.language}»")
    if query.duration_hours is not None and evidence.max_hours is not None:
        details.append(
            f"подходит для {query.duration_hours:g} ч при лимите "
            f"{evidence.max_hours:g} ч"
        )
    if not details:
        details.append(
            f"в профиле указаны рабочие языки: {', '.join(evidence.languages)}"
        )
    return f"{first_sentence} Профиль {' и '.join(details)}."
