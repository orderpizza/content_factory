# Domain Pipelines

**Owner:** Editorial remit and human quality-review criteria.
**Implementation:** `src/workflow/catalog.py` freezes remits;
`src/workflow/gemini_generation.py` owns the executable domain schemas.

A pipeline is a domain, not a social account. Determination assesses all three
and selects at most one angle/job per domain per brief. Each selected route has
one Instagram output binding. Both Detection and human ideas can route into
any appropriate domain. Development destinations are synthetic.

| Pipeline ID | Editorial responsibility |
| --- | --- |
| `english` | Usable expressions, vocabulary and pragmatic context for English learners |
| `ai_tech` | AI capabilities, changes, limitations and practical use |
| `psychology` | Evidence-grounded behavior and communication |

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
quality or complete domain safety.

## Domain review criteria

| Domain | Reviewer checks |
| --- | --- |
| English | Accurate meaning, nuance, register and region; natural examples; suitable audience difficulty; no invented etymology or culture-wide generalization |
| AI / Tech | Dated availability and scope; provider claims distinguished from observed results; no fabricated tests, benchmarks or prices |
| Psychology / Behavior | Observation distinguished from inference; alternative explanations; no diagnosis, invented research or asserted private motives |

## Current domain payloads

All listed fields are required. Scalar values are nonempty strings; list fields
contain 1–12 nonempty strings. Exact JSON shapes are in `DOMAIN_FIELDS`, not a
separate teaching-reference schema.

| Domain | Scalar fields | List fields |
| --- | --- | --- |
| English | target_kind, target, plain_meaning, nuance, register_and_region | usage_notes, avoid_misuse |
| AI / Tech | product_or_feature, change_summary, as_of_context, availability_scope | capabilities, use_cases, limitations |
| Psychology / Behavior | observed_behavior, context, concept, possible_mechanism, example, qualification | alternative_explanations, practical_implications |

The common canonical envelope supplies examples, claims and takeaway separately.
No slide count, caption, geometry or account belongs in a domain payload.
[Content production](../specs/content-production.md) owns that envelope;
[platform outputs](../specs/content-production.md#instagram-package-contract) owns adaptation.
