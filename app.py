"""Streamlit demo for deterministic smart contractor selection."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import streamlit as st

from src import (
    AgentRecommendationResponse,
    RecommendationAgent,
    RecommendationQuery,
    RecommendationTools,
    ResultState,
    load_catalog,
)


DATASET_PATH = Path(__file__).parent / "data" / "hackathon_dataset_anonymized.csv"


@st.cache_resource
def load_runtime() -> tuple[tuple, RecommendationTools]:
    catalog = load_catalog(DATASET_PATH)
    return catalog, RecommendationTools(catalog)


def select_index(options: list[str], preferred: str) -> int:
    return options.index(preferred) if preferred in options else 0


def format_kzt(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₸"


def render_result(
    response: AgentRecommendationResponse,
    query: RecommendationQuery,
    tools: RecommendationTools,
) -> None:
    st.divider()

    if response.state is ResultState.MATCHED:
        st.success(response.message)
    elif response.state is ResultState.CATEGORY_NOT_FOUND:
        st.warning(response.message)
        if response.diagnostics.available_categories:
            st.caption(
                "Categories available in this city: "
                + ", ".join(response.diagnostics.available_categories)
            )
    else:
        st.warning(response.message)
        render_rejection_counts(response)

    mode_label = (
        "OpenAI explanation, checked against deterministic results"
        if response.explanation_mode == "openai"
        else "Deterministic fallback explanation"
    )
    st.caption(f"Explanation mode: {mode_label}")

    for card in response.cards:
        evidence = tools.get_contractor_details(card.contractor_id)
        with st.container(border=True):
            st.subheader(card.contractor_name)
            st.caption(" · ".join(evidence.categories))

            city_column, price_column, availability_column = st.columns(3)
            city_column.metric("City", card.city)
            price_column.metric("Price from", format_kzt(card.price_kzt))
            availability_column.metric(
                "Availability", f"Available {query.event_date.isoformat()}"
            )

            st.markdown(f"**Event formats:** {', '.join(evidence.event_formats)}")
            st.markdown(f"**Languages:** {', '.join(evidence.languages)}")
            duration_text = (
                f"{evidence.max_hours:g} hours"
                if evidence.max_hours is not None
                else "Not specified in the catalog"
            )
            st.markdown(f"**Maximum duration:** {duration_text}")
            st.info(card.explanation)

    render_pipeline_trace(response, query)


def render_rejection_counts(response: AgentRecommendationResponse) -> None:
    labels = {
        "availability": "Busy on selected date",
        "event_format": "Event format mismatch",
        "budget": "Over budget",
        "language": "Language mismatch",
        "duration": "Duration mismatch",
    }
    failures = [
        (labels[reason], count)
        for reason, count in response.diagnostics.rejected_counts.items()
        if count
    ]
    if not failures:
        return

    st.markdown("**Why candidates were rejected**")
    columns = st.columns(len(failures))
    for column, (label, count) in zip(columns, failures):
        column.metric(label, count)


def render_pipeline_trace(
    response: AgentRecommendationResponse, query: RecommendationQuery
) -> None:
    with st.expander("How the AI made this recommendation"):
        st.markdown(
            "Request → deterministic filters → deterministic ranking → "
            "AI or fallback explanation → ID and ordering validation"
        )
        st.write(
            {
                "request": {
                    "city": query.city,
                    "event_date": query.event_date.isoformat(),
                    "event_format": query.event_format,
                    "contractor_category": query.contractor_category,
                    "budget_kzt": query.budget_kzt,
                    "language": query.language,
                    "duration_hours": query.duration_hours,
                },
                "executed_stage_counts": dict(response.diagnostics.stage_counts),
                "first_failure_counts": dict(response.diagnostics.rejected_counts),
                "qualified": response.diagnostics.qualified_count,
                "returned": response.diagnostics.returned_count,
                "explanation_mode": response.explanation_mode,
                "validation": "contractor IDs and deterministic order preserved",
            }
        )


def main() -> None:
    st.set_page_config(
        page_title="Smart Contractor Selection",
        layout="wide",
    )
    st.title("Smart Contractor Selection")
    st.caption("HackAlem AI 2026 · Track 6 · Official 66-contractor catalog")

    catalog, tools = load_runtime()
    cities = sorted({item.city for item in catalog}, key=str.casefold)
    categories = sorted(
        {category for item in catalog for category in item.categories},
        key=str.casefold,
    )
    event_formats = sorted(
        {event_format for item in catalog for event_format in item.event_formats},
        key=str.casefold,
    )
    languages = sorted(
        {language for item in catalog for language in item.languages},
        key=str.casefold,
    )
    calendar_dates = [busy_date for item in catalog for busy_date in item.busy_dates]
    calendar_start = min(calendar_dates)
    calendar_end = max(calendar_dates)
    default_date = date(2026, 11, 10)
    if not calendar_start <= default_date <= calendar_end:
        default_date = calendar_start

    with st.form("recommendation_request"):
        first_row = st.columns(4)
        city = first_row[0].selectbox(
            "City",
            cities,
            index=select_index(cities, "Алматы"),
        )
        event_date = first_row[1].date_input(
            "Event date",
            value=default_date,
            min_value=calendar_start,
            max_value=calendar_end,
        )
        event_format = first_row[2].selectbox(
            "Event format",
            event_formats,
            index=select_index(event_formats, "корпоратив"),
        )
        contractor_category = first_row[3].selectbox(
            "Contractor category",
            categories,
            index=select_index(categories, "Ведущий"),
        )

        second_row = st.columns(3)
        budget_kzt = second_row[0].number_input(
            "Budget KZT",
            min_value=0,
            value=1_000_000,
            step=50_000,
        )
        language_choice = second_row[1].selectbox(
            "Language (optional)",
            ["Any language", *languages],
            index=select_index(["Any language", *languages], "русский"),
        )
        use_duration = second_row[2].checkbox(
            "Specify duration",
            value=True,
        )
        duration_hours = second_row[2].number_input(
            "Duration hours",
            min_value=0.5,
            value=6.0,
            step=0.5,
            disabled=not use_duration,
        )

        submitted = st.form_submit_button(
            "Find contractors",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        query = RecommendationQuery.from_values(
            city=city,
            event_date=event_date,
            event_format=event_format,
            contractor_category=contractor_category,
            budget_kzt=int(budget_kzt),
            duration_hours=float(duration_hours) if use_duration else None,
            language=None if language_choice == "Any language" else language_choice,
        )
        with st.spinner("Checking availability and ranking candidates..."):
            response = RecommendationAgent(tools).recommend(query)
        st.session_state["recommendation_response"] = response
        st.session_state["recommendation_query"] = query

    stored_response = st.session_state.get("recommendation_response")
    stored_query = st.session_state.get("recommendation_query")
    if stored_response is not None and stored_query is not None:
        render_result(stored_response, stored_query, tools)
    else:
        api_status = "configured" if os.getenv("OPENAI_API_KEY") else "not configured"
        st.info(
            "Choose the event requirements and run the recommendation. "
            f"OPENAI_API_KEY is {api_status}; deterministic fallback remains available."
        )


if __name__ == "__main__":
    main()
