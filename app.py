"""Streamlit demo for deterministic smart contractor selection."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src import (
    AgentRecommendationResponse,
    RecommendationAgent,
    RecommendationQuery,
    RecommendationTools,
    ResultState,
    load_catalog,
)


DATASET_PATH = Path(__file__).parent / "data" / "hackathon_dataset_anonymized.csv"
PIPELINE_LABELS = {
    "city": "город",
    "category": "категория",
    "availability": "доступность",
    "event_format": "формат мероприятия",
    "budget": "бюджет",
    "language": "язык",
    "duration": "длительность",
}


@st.cache_resource
def load_runtime() -> tuple[tuple, RecommendationTools]:
    catalog = load_catalog(DATASET_PATH)
    return catalog, RecommendationTools(catalog)


def select_index(options: list[str], preferred: str) -> int:
    return options.index(preferred) if preferred in options else 0


def format_kzt(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₸"


def localized_counts(counts: dict[str, int]) -> dict[str, int]:
    return {PIPELINE_LABELS.get(name, name): count for name, count in counts.items()}


def localized_result_message(
    response: AgentRecommendationResponse, query: RecommendationQuery
) -> str:
    if response.state is ResultState.MATCHED:
        qualified = response.diagnostics.qualified_count
        returned = response.diagnostics.returned_count
        if returned < 3:
            return (
                f"После применения всех ограничений найдено только {qualified}; "
                f"поэтому показано {returned}."
            )
        if qualified > returned:
            return (
                f"Найдено подходящих подрядчиков: {qualified}. "
                f"Показаны первые {returned} по детерминированному рейтингу."
            )
        return f"Найдено подходящих подрядчиков: {returned}."
    if response.state is ResultState.CATEGORY_NOT_FOUND:
        return (
            f"В городе {query.city} нет подрядчиков категории "
            f"«{query.contractor_category}»."
        )
    return (
        f"В городе {query.city} есть подрядчики категории "
        f"«{query.contractor_category}», но после применения ограничений "
        "подходящих кандидатов не осталось."
    )


def render_result(
    response: AgentRecommendationResponse,
    query: RecommendationQuery,
    tools: RecommendationTools,
) -> None:
    st.divider()

    result_message = localized_result_message(response, query)
    if response.state is ResultState.MATCHED:
        st.success(result_message)
    elif response.state is ResultState.CATEGORY_NOT_FOUND:
        st.warning(result_message)
        if response.diagnostics.available_categories:
            st.caption(
                "Категории, доступные в этом городе: "
                + ", ".join(response.diagnostics.available_categories)
            )
    else:
        st.warning(result_message)
        render_rejection_counts(response)

    mode_label = (
        "пояснение OpenAI, проверенное по детерминированным результатам"
        if response.explanation_mode == "openai"
        else "детерминированное резервное пояснение"
    )
    st.caption(f"Режим пояснений: {mode_label}")

    for card in response.cards:
        evidence = tools.get_contractor_details(card.contractor_id)
        with st.container(border=True):
            st.subheader(card.contractor_name)
            st.caption(" · ".join(evidence.categories))

            city_column, price_column, availability_column = st.columns(3)
            city_column.metric("Город", card.city)
            price_column.metric("Цена от", format_kzt(card.price_kzt))
            availability_column.metric(
                "Доступность", f"Свободен {query.event_date.isoformat()}"
            )

            st.markdown(
                f"**Форматы мероприятий:** {', '.join(evidence.event_formats)}"
            )
            st.markdown(f"**Языки:** {', '.join(evidence.languages)}")
            duration_text = (
                f"{evidence.max_hours:g} ч"
                if evidence.max_hours is not None
                else "Не указана в каталоге"
            )
            st.markdown(f"**Максимальная длительность:** {duration_text}")
            st.info(card.explanation)

    render_pipeline_trace(response, query)


def render_rejection_counts(response: AgentRecommendationResponse) -> None:
    labels = {
        "availability": "Занят в выбранную дату",
        "event_format": "Не подходит формат",
        "budget": "Выше бюджета",
        "language": "Не подходит язык",
        "duration": "Не подходит длительность",
    }
    failures = [
        (labels[reason], count)
        for reason, count in response.diagnostics.rejected_counts.items()
        if count
    ]
    if not failures:
        return

    st.markdown("**Почему кандидаты не прошли отбор**")
    columns = st.columns(len(failures))
    for column, (label, count) in zip(columns, failures):
        column.metric(label, count)


def render_pipeline_trace(
    response: AgentRecommendationResponse, query: RecommendationQuery
) -> None:
    with st.expander("Как ИИ сформировал рекомендацию"):
        st.markdown(
            "Запрос → детерминированные фильтры → детерминированный рейтинг → "
            "пояснение ИИ или резервное пояснение → проверка ID и порядка"
        )
        st.write(
            {
                "Запрос": {
                    "Город": query.city,
                    "Дата мероприятия": query.event_date.isoformat(),
                    "Формат мероприятия": query.event_format,
                    "Категория подрядчика": query.contractor_category,
                    "Бюджет, ₸": query.budget_kzt,
                    "Язык": query.language,
                    "Длительность, ч": query.duration_hours,
                },
                "Количество после этапов": localized_counts(
                    dict(response.diagnostics.stage_counts)
                ),
                "Причины первого отказа": localized_counts(
                    dict(response.diagnostics.rejected_counts)
                ),
                "Подходят": response.diagnostics.qualified_count,
                "Показаны": response.diagnostics.returned_count,
                "Режим пояснений": (
                    "OpenAI"
                    if response.explanation_mode == "openai"
                    else "детерминированный резервный"
                ),
                "Проверка": "ID подрядчиков и детерминированный порядок сохранены",
            }
        )


def main() -> None:
    st.set_page_config(
        page_title="Умный подбор подрядчиков",
        layout="wide",
    )
    st.title("Умный подбор подрядчиков")
    st.caption("HackAlem AI 2026 · Трек 6 · Официальный каталог из 66 подрядчиков")

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
            "Город",
            cities,
            index=select_index(cities, "Алматы"),
        )
        event_date = first_row[1].date_input(
            "Дата мероприятия",
            value=default_date,
            min_value=calendar_start,
            max_value=calendar_end,
        )
        event_format = first_row[2].selectbox(
            "Формат мероприятия",
            event_formats,
            index=select_index(event_formats, "корпоратив"),
        )
        contractor_category = first_row[3].selectbox(
            "Категория подрядчика",
            categories,
            index=select_index(categories, "Ведущий"),
        )

        second_row = st.columns(3)
        budget_kzt = second_row[0].number_input(
            "Бюджет, ₸",
            min_value=0,
            value=1_000_000,
            step=50_000,
        )
        language_choice = second_row[1].selectbox(
            "Язык (необязательно)",
            ["Любой язык", *languages],
            index=select_index(["Любой язык", *languages], "русский"),
        )
        use_duration = second_row[2].checkbox(
            "Указать длительность",
            value=True,
        )
        duration_hours = second_row[2].number_input(
            "Длительность, ч",
            min_value=0.5,
            value=6.0,
            step=0.5,
            disabled=not use_duration,
        )

        submitted = st.form_submit_button(
            "Подобрать подрядчиков",
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
            language=None if language_choice == "Любой язык" else language_choice,
        )
        with st.spinner("Проверяем доступность и ранжируем кандидатов..."):
            response = RecommendationAgent(tools).recommend(query)
        st.session_state["recommendation_response"] = response
        st.session_state["recommendation_query"] = query

    stored_response = st.session_state.get("recommendation_response")
    stored_query = st.session_state.get("recommendation_query")
    if stored_response is not None and stored_query is not None:
        render_result(stored_response, stored_query, tools)
    else:
        api_status = "настроен" if os.getenv("OPENAI_API_KEY") else "не настроен"
        st.info(
            "Выберите параметры мероприятия и запустите подбор. "
            f"OPENAI_API_KEY {api_status}; резервные детерминированные пояснения "
            "всегда доступны."
        )


if __name__ == "__main__":
    main()
