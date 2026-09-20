# Domain Pipelines

**Owner:** Editorial remit and human quality-review criteria.
**Implementation:** `src/workflow/catalog.py` freezes remits;
`src/workflow/gemini_generation.py` owns the executable domain schemas.

A pipeline is a domain, not a social account. Determination assesses all five
and selects at most one angle/job per domain per brief. Each selected route has
at most one Instagram and one X output binding. Development bindings are
synthetic; real accounts are separately configured.

| Pipeline ID | Editorial responsibility |
| --- | --- |
| `english` | Usable expressions, vocabulary and pragmatic context for English learners |
| `ai_tools` | AI capabilities, changes, limitations and practical use |
| `personal_finance` | Consumer financial implications and tradeoffs |
| `business_side_hustle` | Commercial mechanisms and realistic entrepreneurial opportunities |
| `psychology_behavior` | Evidence-grounded behavior and communication |

## Shared quality policy

Every selected angle should offer distinct reader value, fit its audience and
have sufficient evidence. Popularity establishes attention, not factual truth.
Skipping a weak domain is preferable to forcing an analogy.

Generation receives frozen evidence and has no browsing/tool-use ability.
Sources must not be invented. Hypothetical examples and qualified inferences
must be distinguishable from source-bound facts. Commercial promises,
sponsorship claims and affiliate links need explicit support and disclosure.

These are prompt and human-review criteria. Current validators check closed
fields, cardinality and reference IDs—not factual entailment, pedagogical
quality or complete domain safety. [The roadmap](../plans/target-implementation.md)
owns stronger validation and reference catalogs.

## Domain review criteria

| Domain | Reviewer checks |
| --- | --- |
| English | Accurate meaning, nuance, register and region; natural examples; suitable audience difficulty; no invented etymology or culture-wide generalization |
| AI / Tools | Dated availability and scope; provider claims distinguished from observed results; no fabricated tests, benchmarks or prices |
| Personal Finance | Jurisdiction/population, dated context and uncertainty; educational rather than personalized advice; no guaranteed return or unsupported causal forecast |
| Business / Side Hustles | Customer problem, mechanism, prerequisites and risks; hypotheses distinguished from demand/revenue evidence; no deceptive marketing |
| Psychology / Behavior | Observation distinguished from inference; alternative explanations; no diagnosis, invented research or asserted private motives |

## Current domain payloads

All listed fields are required. Scalar values are nonempty strings; list fields
contain 1–12 nonempty strings. Exact JSON shapes are in `DOMAIN_FIELDS`, not a
separate teaching-reference schema.

| Domain | Scalar fields | List fields |
| --- | --- | --- |
| English | target_kind, target, plain_meaning, nuance, register_and_region | usage_notes, avoid_misuse |
| AI / Tools | product_or_feature, change_summary, as_of_context, availability_scope | capabilities, use_cases, limitations |
| Personal Finance | event_or_topic, as_of_context, jurisdiction_or_population, mechanism, uncertainty, disclaimer | consumer_implications, watch_points |
| Business / Side Hustles | customer_problem, opportunity_hypothesis, mechanism | examples, prerequisites, costs_and_risks, validation_actions |
| Psychology / Behavior | observed_behavior, context, concept, possible_mechanism, example, qualification | alternative_explanations, practical_implications |

The common canonical envelope supplies examples, claims and takeaway separately.
No slide count, caption, geometry or account belongs in a domain payload.
[Content production](../specs/content-production.md) owns that envelope;
[platform outputs](../specs/platform-outputs.md) owns adaptation.
