from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src import (
    ExplanationDraft,
    ExplanationItem,
    RecommendationAgent,
    RecommendationQuery,
    RecommendationTools,
    ResultState,
    load_catalog,
)


DATASET = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "hackathon_dataset_anonymized.csv"
)


class StaticProvider:
    mode = "mock_ai"

    def __init__(self, draft: ExplanationDraft) -> None:
        self._draft = draft

    def generate(self, query, result, evidence) -> ExplanationDraft:
        return self._draft


class EvidenceEchoProvider:
    mode = "mock_ai"

    def generate(self, query, result, evidence) -> ExplanationDraft:
        return ExplanationDraft(
            summary=result.message,
            explanations=tuple(
                ExplanationItem(
                    contractor_id=item.contractor_id,
                    explanation=(
                        f"Evidence for {item.contractor_id}: {item.contractor_name} "
                        f"supports {query.event_format} at {item.price_from_kzt} ₸."
                    ),
                )
                for item in evidence
            ),
        )


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(DATASET)
        cls.tools = RecommendationTools(cls.catalog)

    @staticmethod
    def matched_query() -> RecommendationQuery:
        return RecommendationQuery.from_values(
            city="Алматы",
            event_date="2026-11-10",
            event_format="корпоратив",
            contractor_category="Ведущий",
            budget_kzt=1_000_000,
            duration_hours=6,
            language="русский",
        )

    @staticmethod
    def no_match_query() -> RecommendationQuery:
        return RecommendationQuery.from_values(
            city="Астана",
            event_date="2026-09-24",
            event_format="корпоратив",
            contractor_category="Банкетный зал",
            budget_kzt=1_000_000,
            duration_hours=6,
            language="русский",
        )

    def deterministic_ids(self) -> tuple[str, ...]:
        result = self.tools.search_contractors(self.matched_query())
        return tuple(item.contractor.id for item in result.recommendations)

    def test_agent_cannot_introduce_rejected_contractor(self) -> None:
        expected_ids = self.deterministic_ids()
        deterministic = self.tools.search_contractors(self.matched_query())
        malicious = ExplanationDraft(
            summary=deterministic.message,
            explanations=(
                ExplanationItem("HK-72938", "Invented candidate."),
                *(ExplanationItem(item, "Valid candidate.") for item in expected_ids),
            ),
        )
        response = RecommendationAgent(
            self.tools, StaticProvider(malicious)
        ).recommend(self.matched_query())
        self.assertEqual(tuple(card.contractor_id for card in response.cards), expected_ids)
        self.assertEqual(response.explanation_mode, "deterministic_fallback")

    def test_agent_cannot_reorder_recommendations(self) -> None:
        expected_ids = self.deterministic_ids()
        deterministic = self.tools.search_contractors(self.matched_query())
        reordered = ExplanationDraft(
            summary=deterministic.message,
            explanations=tuple(
                ExplanationItem(item, "Reordered explanation.")
                for item in reversed(expected_ids)
            ),
        )
        response = RecommendationAgent(
            self.tools, StaticProvider(reordered)
        ).recommend(self.matched_query())
        self.assertEqual(tuple(card.contractor_id for card in response.cards), expected_ids)
        self.assertEqual(response.explanation_mode, "deterministic_fallback")

    def test_explanations_stay_associated_with_contractor_ids(self) -> None:
        response = RecommendationAgent(
            self.tools, EvidenceEchoProvider()
        ).recommend(self.matched_query())
        self.assertEqual(response.explanation_mode, "mock_ai")
        for card in response.cards:
            self.assertIn(card.contractor_id, card.explanation)
            self.assertIn(card.contractor_name, card.explanation)

    def test_generic_ai_explanation_is_rejected(self) -> None:
        deterministic = self.tools.search_contractors(self.matched_query())
        generic = ExplanationDraft(
            summary=deterministic.message,
            explanations=tuple(
                ExplanationItem(item.contractor.id, "A great choice for your event.")
                for item in deterministic.recommendations
            ),
        )
        response = RecommendationAgent(
            self.tools, StaticProvider(generic)
        ).recommend(self.matched_query())
        self.assertEqual(response.explanation_mode, "deterministic_fallback")

    def test_category_not_found_is_handled(self) -> None:
        query = RecommendationQuery.from_values(
            city="Астана",
            event_date="2026-09-24",
            event_format="корпоратив",
            contractor_category="Инструменталист",
            budget_kzt=1_000_000,
        )
        response = RecommendationAgent(
            self.tools, EvidenceEchoProvider()
        ).recommend(query)
        self.assertEqual(response.state, ResultState.CATEGORY_NOT_FOUND)
        self.assertEqual(response.cards, ())
        self.assertIn("Инструменталист", response.message)
        self.assertIn("Астана", response.message)

    def test_no_match_uses_deterministic_diagnostics(self) -> None:
        response = RecommendationAgent(
            self.tools, EvidenceEchoProvider()
        ).recommend(self.no_match_query())
        self.assertEqual(response.state, ResultState.NO_MATCH)
        self.assertEqual(response.cards, ())
        self.assertEqual(response.diagnostics.rejected_counts["budget"], 1)
        self.assertIn("budget=1", response.message)

    def test_missing_api_key_uses_fallback_without_crashing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = RecommendationAgent(self.tools).recommend(self.matched_query())
        self.assertEqual(response.state, ResultState.MATCHED)
        self.assertEqual(response.explanation_mode, "deterministic_fallback")
        self.assertTrue(all(card.explanation for card in response.cards))

    def test_final_output_contains_at_most_three_contractors(self) -> None:
        response = RecommendationAgent(
            self.tools, EvidenceEchoProvider()
        ).recommend(self.matched_query())
        self.assertLessEqual(len(response.cards), 3)


if __name__ == "__main__":
    unittest.main()
