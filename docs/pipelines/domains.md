# Phase 1 Domain Pipelines

**Document role:** Tier 2 domain/intelligence contract.
**Owner:** Domain remit, angle eligibility, domain-specific canonical content,
and editorial validation. Shared production mechanics belong to
[Content production](../specs/content-production.md); platform copy and layout
belong to [Platform outputs](../specs/platform-outputs.md).

## Identity and distribution intent

`domain_pipeline_catalog_v1` contains exactly these five stable pipeline IDs.
The catalog describes supported design, not which workers currently run.

| Pipeline ID | Instagram intent | X intent | Account identity |
| --- | --- | --- | --- |
| `english` | Primary | Optional | O2English brand; primary Instagram account key `o2_english` |
| `ai_tools` | Yes | Yes | Operator-defined destination bindings |
| `personal_finance` | Yes | Yes | Operator-defined destination bindings |
| `business_side_hustle` | Yes | Yes | Operator-defined destination bindings |
| `psychology_behavior` | Yes | Optional/yes | Operator-defined destination bindings |

A pipeline does not own credentials, account IDs, platform formats, renderer
geometry, or delivery calls. One versioned pipeline implementation can serve
several configured destinations through output bindings. Undefined accounts
remain unbound, not invented placeholder accounts eligible for publication.
Account names other than `o2_english` are not domain enums or code constants.

## Shared editorial rules

Each selected pipeline receives one frozen angle from Determination. It creates
one canonical content object under that angle, not a platform-specific carousel.
A proposed initial limit of one angle per pipeline per revision bounds Phase 1
fan-out at five canonical jobs; adding multiple angles per domain requires a
new routing policy. This does not require all five to be selected.

A route needs a useful audience outcome, a credible connection to the trend or
human idea, and enough evidence for its claims. Trend popularity is evidence of
attention only. Titles, view counts, and snippets do not establish causal,
financial, scientific, product-performance, or language-usage claims. A weak
connection is a skip, not an invitation to generate a forced analogy.

Sources are bounded, frozen, provenance-bearing evidence entries or
operator-approved reference assertions. Generation has no autonomous browsing
or tool-use capability. If evidence is insufficient, block/skip with a concrete
reason and request evidence through the existing Intake/revision path. Do not
quietly add a research worker or let Gemini invent missing facts.

Monetization potential may be recorded as an internal, qualified hypothesis.
It is not an earnings forecast or requirement for acceptance. Sponsored claims,
affiliate URLs, prices, and commercial CTAs require approved, dated source and
disclosure policy before adaptation includes them. Phase 1 has no automated
affiliate enrollment or advertising-sales workflow.

## English — `english`

Remit: useful expressions, vocabulary, phrases, idiomatic usage, and culturally
relevant language. A current event may inspire a teaching target when the
connection is natural; English is no longer restricted to idioms. Default
audience remains CEFR B1–B2, output locale `en-US`, with relevant regional and
register context identified rather than presented as universal usage.

Canonical extension `english_teaching_v2` requires `target_kind` (expression,
vocabulary, phrase, or cultural_usage), `target`, `intended_sense`,
`plain_meaning`, `nuance`, `register_and_region`, `usage_notes`, `avoid_misuse`,
and structured generated examples/dialogue. No slide count, caption, hashtags,
pixel size, or social account belongs in this extension.

Each meaning, nuance, register, region, and usage assertion must resolve to a
target- and sense-compatible entry in the frozen operator-approved teaching
reference catalog. Entries retain `reference_id`, immutable version,
`approved_at`, `approved_by`, active/superseded state, and bounded typed
assertions with supported claim IDs. Changed assertions create new versions.
Generated examples are marked as generated; trend evidence is never relabeled
as a teaching assertion. No uncontrolled web lookup or model memory substitutes
for missing reference support. Expand the catalog schema for vocabulary and
sense identity before enabling those targets; the old idiom-only draft is not
the implementation schema.

Validation must check reference target/sense/type, CEFR suitability, natural
usage, and consistency of every example with the frozen teaching objective.
Reject unsupported etymology, slurs/offensive teaching targets, exaggerated
fluency promises, or misleading culture-wide generalizations. Internal teaching
references are audit metadata and need not become public citations; preserve
any actual licensing/attribution requirement of source material.

## AI / Tools — `ai_tools`

Remit: AI developments, models/products/tools, important ecosystem changes, and
practical applications. A strong angle explains what changed, what it does,
why it matters to the chosen audience, and a supported use case.

Canonical extension: product/feature, change and announcement date, known
availability/scope, supported capabilities, practical use cases, limitations,
and claim-to-source references. Separate provider claims from independently
observed results. Do not invent benchmarks, access tiers, availability, current
prices, or hands-on testing. Date-sensitive claims need explicit as-of context.
Affiliate/sponsorship potential stays internal unless approved for public use.

## Money / Personal Finance — `personal_finance`

Remit: economic developments, consumer finance, interest rates, and market
events with an ordinary-user consequence. The angle explains an event simply,
its supported financial implications, and what readers should understand/watch.

Canonical extension: event/as-of date, jurisdiction or applicable population,
mechanism, consumer implications, uncertainty, and watch-points with sources.
This is general financial education, not personalized investment, tax, credit,
or legal advice. No buy/sell instruction, guaranteed outcome, precise forecast
without evidence, or unsupported causal link. Hypothetical numerical examples
must be labeled and reproducibly computed; a disclaimer cannot rescue an
unsupported claim. Missing jurisdiction or dated evidence may block a route.

## Business / Side Hustles — `business_side_hustle`

Remit: commercial implications, entrepreneurship, side hustles, changing
business models, and opportunities/problems created by technology or culture.

Canonical extension: affected customer/problem, opportunity hypothesis,
mechanism, examples, prerequisites, costs/risks, and low-commitment validation
actions. Distinguish a plausible business idea from demonstrated demand or
profitability. Never fabricate revenue, claim guaranteed earnings, or encourage
deceptive marketing. Examples may be hypothetical when clearly labeled; claims
about real businesses require support.

## Psychology / Human Behavior — `psychology_behavior`

Remit: social/workplace behavior, relationships, communication, and cautious
psychological interpretation of culturally relevant events.

Canonical extension: observed behavior, context, evidence-backed concept,
possible mechanism, alternative explanations, example, and practical
communication/behavioral implication. Distinguish observation from inference;
do not diagnose a person from viral material, assert private motives, invent
research, or present pop-psychology certainty. Clinical claims or advice fall
outside this educational pipeline. A possible mechanism must remain qualified
in every adapted format.

## Routing experiment and acceptance

For an AI shopping-agent launch, several angles might be justified: supported
tool capabilities; consumer spending implications; merchant opportunities;
qualified trust/agency behavior; or a naturally relevant English expression.
These are candidate hypotheses, not five mandatory outputs. A headline alone
does not substantiate all of them.

Fixtures must cover each domain independently and combinations of domains.
Validate distinct angle/claim objectives, intentionally skipped weak links,
whole-trend rejection, insufficient evidence, disabled/unbound destinations,
domain-specific unsafe claims, and the same canonical content reused across
Instagram and X. Operator evaluation of semantic quality complements schema
validation; syntactic validity alone does not prove credible content.
