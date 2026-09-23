# Smart Contractor Selection MVP Specification

## 1. Problem

The customer has already chosen an event type and received an existing contractor catalog for a city. The product must help select the best candidates from that catalog, not expand the catalog or generate new contractor profiles.

The system recommends at most 3 contractors from `data/hackathon_dataset_anonymized.csv` using deterministic constraints first, then lightweight AI only for semantic relevance and human-readable explanations.

## 2. Target User

An event customer or event manager who knows the city, event date, event format, contractor category, and budget, and wants a short, evidence-based shortlist instead of browsing the full catalog manually.

## 3. MVP Goal

Build a deterministic, explainable recommender that:

- Filters the official 66-profile catalog by city, contractor category, availability, budget, event format, optional language, and optional duration.
- Returns `MATCHED`, `CATEGORY_NOT_FOUND`, or `NO_MATCH`.
- Shows up to 3 contractor cards with concrete evidence-based explanations.
- Produces the same ordering for the same exact input.
- Responds in under approximately 10 seconds.

This scope is intended for one developer with about 5 hours of total hackathon development time.

## 4. Non-Goals

- Do not create synthetic contractor data.
- Do not modify `data/hackathon_dataset_anonymized.csv`.
- Do not replace the official dataset schema.
- Do not scrape or enrich contractor profiles from external sources.
- Do not build marketplace expansion, contractor onboarding, payments, booking, messaging, or calendar synchronization.
- Do not introduce a multi-agent architecture.
- Do not let the AI override hard constraints.

## 5. Input Contract

Required input fields:

| Field | Type | Expected values / rule |
| --- | --- | --- |
| `city` | string | Must match a dataset city value, e.g. `Алматы`, `Астана`, `Зарубежье`. |
| `event_date` | string | ISO date `YYYY-MM-DD`; compare directly against pipe-delimited `busy_dates`. Dataset availability covers 2026-09-23 through 2026-12-31. |
| `event_format` | string | Must match one value inside dataset `event_formats`, e.g. `свадьба`, `корпоратив`, `юбилей`, `той`, `конференция`, `день рождения`. |
| `contractor_category` | string | Match as membership inside pipe-delimited `categories`, not exact full-cell equality. Examples: `Ведущий`, `Фотограф`, `Банкетный зал`, `Шоу-программа`. |
| `budget_kzt` | integer | Contractor qualifies only when `price_from_kzt <= budget_kzt`. |

Optional input fields:

| Field | Type | Expected values / rule |
| --- | --- | --- |
| `duration_hours` | number | If provided and contractor `max_hours` is non-empty, require `max_hours >= duration_hours`. If `max_hours` is empty, treat duration capacity as unspecified and do not filter solely on duration. |
| `language` | string | If provided, require membership inside pipe-delimited `languages`, e.g. `русский`, `казахский`, `английский`. |

Normalization for MVP:

- Trim whitespace from all string inputs.
- Compare values case-insensitively where practical, but output original dataset values.
- Do not translate values automatically in the MVP; UI/examples should use the dataset's Russian labels.

## 6. Dataset Contract

Use only the official CSV:

`data/hackathon_dataset_anonymized.csv`

Observed dataset size:

- 66 contractor profiles.

Observed columns:

- `id`
- `anon_name`
- `categories`
- `city`
- `city_imputed`
- `synthetic`
- `price_from_kzt`
- `price_imputed`
- `event_formats`
- `languages`
- `max_hours`
- `busy_dates`
- `description`

Observed value structure:

- `categories` is pipe-delimited and may contain multiple categories, such as `Банкетный зал|Загородная площадка|Ресторан`.
- `event_formats` is pipe-delimited.
- `languages` is pipe-delimited.
- `busy_dates` is pipe-delimited ISO dates.
- `max_hours` may be blank.
- `price_from_kzt` is numeric; `price_imputed` indicates whether price was filled during dataset preparation.
- `city_imputed` indicates whether city was imputed.
- `synthetic` exists in the official dataset and should be displayed or logged only if useful for debugging; it is not a ranking criterion for MVP.

Observed cities:

- `Алматы`: 50 profiles
- `Астана`: 15 profiles
- `Зарубежье`: 1 profile

Observed split categories include:

- `Банкетный зал`
- `Ведущий`
- `Ведущий церемонии`
- `Видеограф`
- `Декоратор`
- `Загородная площадка`
- `Инструменталист`
- `Лайв-бэнд`
- `Национальный ансамбль`
- `Отель`
- `Подарки и сувениры`
- `Ресторан`
- `Танцевальный коллектив`
- `Флорист`
- `Фото и видеобудки`
- `Фотограф`
- `Шоу-программа`

Observed event formats:

- `свадьба`
- `корпоратив`
- `юбилей`
- `той`
- `конференция`
- `день рождения`

Observed languages:

- `русский`
- `казахский`
- `английский`

## 7. Output Contract

Return a structured response with:

- `state`: one of `MATCHED`, `CATEGORY_NOT_FOUND`, `NO_MATCH`
- `message`: short human-readable summary
- `cards`: list of 0 to 3 contractor cards
- `diagnostics`: concise counts explaining the pipeline, suitable for judge/demo visibility

Each contractor card must contain:

| Field | Source / rule |
| --- | --- |
| `contractor_name` | `anon_name` |
| `category` | Matching requested category, or original `categories` if displaying all categories is clearer |
| `city` | `city` |
| `price` | `price_from_kzt` formatted as KZT |
| `explanation` | 1-2 specific sentences referencing concrete evidence |

Explanations must reference concrete evidence from the row and input, such as:

- price is within budget
- requested event date is not in `busy_dates`
- event format appears in `event_formats`
- requested language appears in `languages`
- `max_hours` covers `duration_hours` when known
- description semantically matches the event need

Generic explanations like "this is a great choice for your event" are not acceptable.

If fewer than 3 contractors qualify, the `message` must explain why fewer were returned, e.g. "Only 2 contractors in Алматы matched category, date, budget, format, and language constraints."

## 8. Result States

### `MATCHED`

One or more suitable contractors were found after applying all hard constraints.

Response:

- `cards` contains 1 to 3 contractors.
- `message` states how many qualified and whether fewer than 3 were available.

### `CATEGORY_NOT_FOUND`

The requested contractor category does not exist in the selected city.

Definition:

- After filtering by `city`, no row has `contractor_category` as a member of pipe-delimited `categories`.

Response:

- `cards` is empty.
- `message` names the missing category and selected city.
- The system may show available categories in that city as a diagnostic, but should not recommend another category.

### `NO_MATCH`

Contractors of the requested category exist in the selected city, but none survive all constraints.

Typical causes:

- all are busy on `event_date`
- all exceed `budget_kzt`
- none support `event_format`
- none support requested `language`
- known `max_hours` is below requested `duration_hours`

Response:

- `cards` is empty.
- `message` explains the main failing constraints using counts, e.g. "3 photographers exist in Астана, but 2 exceed the budget and the remaining one is busy on 2026-09-25."

## 9. Hard Constraints

Apply hard constraints deterministically before any AI call:

1. City must equal requested `city`.
2. Requested `contractor_category` must be a member of pipe-delimited `categories`.
3. Requested `event_date` must not be a member of pipe-delimited `busy_dates`.
4. `price_from_kzt <= budget_kzt`.
5. Requested `event_format` must be a member of pipe-delimited `event_formats`.
6. If `language` is provided, it must be a member of pipe-delimited `languages`.
7. If `duration_hours` is provided and `max_hours` is non-empty, `max_hours >= duration_hours`.

The availability rule is absolute: a contractor whose `busy_dates` contains the requested `event_date` must never appear in recommendations.

## 10. Ranking Principles

Ranking must be deterministic. Recommended order:

1. Hard-filter eligible candidates.
2. Compute deterministic feature scores:
   - budget fit: lower `price_from_kzt / budget_kzt` is better, without rewarding irrelevant underpricing too aggressively
   - event format match: required as hard filter; optionally reward descriptions mentioning similar event context
   - language match: required only when requested; slight boost for multilingual support when language is requested
   - duration fit: if `duration_hours` and `max_hours` are known, closer but sufficient capacity may rank above excessive capacity
   - semantic relevance: AI or embedding-based score from `description` against the user's event context
3. Tie-break deterministically by:
   - lower `price_from_kzt`
   - then `anon_name`
   - then `id`

The same exact input and dataset must always produce the same contractor ordering. If using an LLM for semantic scoring, force deterministic settings where available and persist the score only for the current request; final tie-breaks must remain deterministic.

## 11. Agentic Workflow

Use a minimal, explainable workflow with one orchestrator:

1. Parse and validate user input.
2. Load the official CSV.
3. Split pipe-delimited fields into lists for `categories`, `event_formats`, `languages`, and `busy_dates`.
4. Filter by `city`.
5. Check category existence in that city:
   - if no category exists, return `CATEGORY_NOT_FOUND`.
6. Apply hard constraints: availability, budget, format, language, duration.
7. If no candidates remain, return `NO_MATCH` with deterministic failure-count explanation.
8. Rank remaining candidates deterministically.
9. Use AI only to assist with semantic relevance from `description` and to draft 1-2 sentence evidence-based explanations.
10. Validate generated explanations before returning:
   - must mention concrete evidence
   - must not claim unsupported facts
   - must not recommend busy contractors
11. Return up to 3 cards and diagnostics.

The AI layer is advisory. Python logic owns eligibility, status selection, count diagnostics, sorting tie-breaks, and final safety checks.

## 12. Proposed Agent Tools

Minimal conceptual tool set:

1. `load_catalog`
   - Reads `data/hackathon_dataset_anonymized.csv`.
   - Returns normalized rows and split list fields.

2. `filter_contractors`
   - Applies city, category, availability, budget, event format, language, and duration constraints.
   - Produces candidate rows plus rejection counts by reason.

3. `rank_contractors`
   - Applies deterministic feature scoring and stable tie-breaks.
   - Optionally receives semantic relevance scores from the AI layer.

4. `semantic_match_and_explain`
   - AI-assisted.
   - Input is only already-eligible candidates plus the user request.
   - Outputs semantic notes and explanation drafts grounded in row fields.

5. `validate_response`
   - Deterministically checks final cards against hard constraints.
   - Rejects generic or unsupported explanations.

No additional agents are required.

## 13. Killer Demo Scenario

Use real dataset values and show the pipeline counts on screen or in logs.

### Dense-category query where ranking matters

Input:

- `city`: `Алматы`
- `event_date`: `2026-11-10`
- `event_format`: `корпоратив`
- `contractor_category`: `Ведущий`
- `budget_kzt`: `1000000`
- `duration_hours`: `6`
- `language`: `русский`

Expected behavior:

- Multiple Алматы hosts qualify, so ranking matters.
- Cards should explain budget, corporate format, Russian language, availability, and duration where available.

### Rare-category query

Input:

- `city`: `Алматы`
- `event_date`: `2026-09-24`
- `event_format`: `корпоратив`
- `contractor_category`: `Фото и видеобудки`
- `budget_kzt`: `500000`
- `duration_hours`: `6`
- `language`: `русский`

Expected behavior:

- Small candidate set.
- Return fewer than 3 if only 1-2 qualify, with an explicit message.

### No-result query

Input:

- `city`: `Астана`
- `event_date`: `2026-09-24`
- `event_format`: `корпоратив`
- `contractor_category`: `Банкетный зал`
- `budget_kzt`: `1000000`
- `duration_hours`: `6`
- `language`: `русский`

Expected behavior:

- Category exists in Астана, but the available banquet hall price is above this budget.
- Return `NO_MATCH`, not `CATEGORY_NOT_FOUND`.

### Date-sensitive availability query

Use the same input except change only `event_date`:

- `city`: `Алматы`
- `event_format`: `корпоратив`
- `contractor_category`: `Ведущий`
- `budget_kzt`: `1000000`
- `duration_hours`: `6`
- `language`: `русский`

Compare:

- `event_date`: `2026-09-23`
- `event_date`: `2026-09-24`

Expected behavior:

- Results differ because some hosts have one date in `busy_dates` and not the other.

### Determinism check

Repeat the dense-category query twice with identical input.

Expected behavior:

- Same state.
- Same contractor ordering.
- Same or materially identical evidence-based explanations.

## 14. Acceptance Criteria

- Uses `data/hackathon_dataset_anonymized.csv` without modifying it.
- Reads the actual dataset columns listed in this spec.
- Treats pipe-delimited fields as multi-value lists.
- Returns at most 3 contractor cards.
- Never returns a contractor busy on the requested date.
- Correctly distinguishes `MATCHED`, `CATEGORY_NOT_FOUND`, and `NO_MATCH`.
- Explains fewer-than-3 results when applicable.
- Explanations include concrete evidence and avoid generic praise.
- Ranking is deterministic for identical input.
- AI use is limited to semantic relevance and explanation generation for already-eligible candidates.
- Internal pipeline counts are available for judge explanation.
- MVP supports dense category, rare category, no-result, date-sensitive, and repeated-query demos.
- Target response time is under approximately 10 seconds on the 66-row dataset.

## 15. Definition of Done

- One runnable MVP flow accepts the input contract and returns the output contract.
- The recommender passes manual tests for all killer demo scenarios.
- Hard constraints are implemented in deterministic Python logic.
- Final response validation prevents busy contractors and unsupported explanations from appearing.
- The official dataset and preview HTML remain unchanged.
- No synthetic contractor rows or replacement schema are introduced.
- The implementation can be explained to judges as: "deterministic filters first, deterministic ranking and tie-breaks second, AI only for semantic relevance and grounded explanations."
