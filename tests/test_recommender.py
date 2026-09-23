from __future__ import annotations

import unittest
from pathlib import Path

from src import (
    ContractorRecommender,
    RecommendationQuery,
    ResultState,
    load_catalog,
)


DATASET = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "hackathon_dataset_anonymized.csv"
)


class RecommenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(DATASET)
        cls.recommender = ContractorRecommender(cls.catalog)

    @staticmethod
    def dense_query(event_date: str = "2026-11-10") -> RecommendationQuery:
        return RecommendationQuery.from_values(
            city="Алматы",
            event_date=event_date,
            event_format="корпоратив",
            contractor_category="Ведущий",
            budget_kzt=1_000_000,
            duration_hours=6,
            language="русский",
        )

    def test_catalog_loads_and_normalizes_official_rows(self) -> None:
        self.assertEqual(len(self.catalog), 66)
        multi_category = next(item for item in self.catalog if item.id == "HK-35846")
        self.assertEqual(
            multi_category.categories, ("Фото и видеобудки", "Шоу-программа")
        )
        self.assertIn("корпоратив", multi_category.event_formats)
        self.assertIn("русский", multi_category.languages)

    def test_busy_contractor_is_excluded(self) -> None:
        result = self.recommender.recommend(self.dense_query("2026-09-23"))
        returned_ids = {
            item.contractor.id for item in result.recommendations
        }
        self.assertNotIn("HK-44733", returned_ids)
        self.assertGreater(result.diagnostics.rejected_counts["availability"], 0)

    def test_multi_category_contractor_matches(self) -> None:
        query = RecommendationQuery.from_values(
            city="Алматы",
            event_date="2026-09-24",
            event_format="корпоратив",
            contractor_category="Фото и видеобудки",
            budget_kzt=500_000,
            duration_hours=6,
            language="русский",
        )
        result = self.recommender.recommend(query)
        returned_ids = [item.contractor.id for item in result.recommendations]
        self.assertEqual(result.state, ResultState.MATCHED)
        self.assertIn("HK-35846", returned_ids)

    def test_category_not_found(self) -> None:
        query = RecommendationQuery.from_values(
            city="Астана",
            event_date="2026-09-24",
            event_format="корпоратив",
            contractor_category="Инструменталист",
            budget_kzt=1_000_000,
        )
        result = self.recommender.recommend(query)
        self.assertEqual(result.state, ResultState.CATEGORY_NOT_FOUND)
        self.assertEqual(result.recommendations, ())

    def test_no_match(self) -> None:
        query = RecommendationQuery.from_values(
            city="Астана",
            event_date="2026-09-24",
            event_format="корпоратив",
            contractor_category="Банкетный зал",
            budget_kzt=1_000_000,
            duration_hours=6,
            language="русский",
        )
        result = self.recommender.recommend(query)
        self.assertEqual(result.state, ResultState.NO_MATCH)
        self.assertEqual(result.diagnostics.rejected_counts["budget"], 1)

    def test_matched_returns_at_most_three(self) -> None:
        result = self.recommender.recommend(self.dense_query())
        self.assertEqual(result.state, ResultState.MATCHED)
        self.assertLessEqual(len(result.recommendations), 3)

    def test_same_input_has_same_order(self) -> None:
        first = self.recommender.recommend(self.dense_query())
        second = self.recommender.recommend(self.dense_query())
        first_ids = [item.contractor.id for item in first.recommendations]
        second_ids = [item.contractor.id for item in second.recommendations]
        self.assertEqual(first_ids, second_ids)

    def test_different_dates_change_results_due_to_availability(self) -> None:
        first = self.recommender.recommend(self.dense_query("2026-09-23"))
        second = self.recommender.recommend(self.dense_query("2026-09-24"))
        first_ids = [item.contractor.id for item in first.recommendations]
        second_ids = [item.contractor.id for item in second.recommendations]
        self.assertNotEqual(first_ids, second_ids)

    def test_optional_language_filter(self) -> None:
        query = RecommendationQuery.from_values(
            city="Алматы",
            event_date="2026-11-10",
            event_format="корпоратив",
            contractor_category="Ведущий",
            budget_kzt=2_000_000,
            language="английский",
        )
        result = self.recommender.recommend(query)
        self.assertEqual(result.state, ResultState.MATCHED)
        for item in result.recommendations:
            self.assertIn("английский", item.contractor.languages)
        self.assertGreater(result.diagnostics.rejected_counts["language"], 0)

    def test_known_duration_capacity_is_enforced(self) -> None:
        query = RecommendationQuery.from_values(
            city="Алматы",
            event_date="2026-09-24",
            event_format="свадьба",
            contractor_category="Национальный ансамбль",
            budget_kzt=500_000,
            duration_hours=3,
            language="казахский",
        )
        result = self.recommender.recommend(query)
        self.assertEqual(result.state, ResultState.NO_MATCH)
        self.assertGreater(result.diagnostics.rejected_counts["duration"], 0)

    def test_blank_max_hours_does_not_reject(self) -> None:
        query = RecommendationQuery.from_values(
            city="Алматы",
            event_date="2026-09-23",
            event_format="корпоратив",
            contractor_category="Флорист",
            budget_kzt=200_000,
            duration_hours=100,
            language="русский",
        )
        result = self.recommender.recommend(query)
        returned_ids = [item.contractor.id for item in result.recommendations]
        self.assertEqual(result.state, ResultState.MATCHED)
        self.assertIn("HK-39372", returned_ids)
        contractor = next(
            item.contractor
            for item in result.recommendations
            if item.contractor.id == "HK-39372"
        )
        self.assertIsNone(contractor.max_hours)


if __name__ == "__main__":
    unittest.main()
