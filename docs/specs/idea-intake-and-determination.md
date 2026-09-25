# Idea Intake and Determination Specification

**Document role:** Tier 2 current planning contract.
**Owner:** Human conversation, immutable briefs, three-domain decisions and editorial planning.

## Two entry paths

Detection selects a cluster and atomically creates a trend ContentThread,
source-backed BriefRevision and DeterminationRequest. No Intake call is required.
Human input creates a message and IntakeRequest; Intake may clarify or freeze a
brief and DeterminationRequest. Both paths meet at the same routing boundary.

Every cross-stage handoff is persisted SQLite state. Dashboard/CLI commands
never invoke Gemini directly.

Storage measurements are advisory for these paths, including Gemini claims and
ContentJob creation. Missing/stale/clock-invalid or low-space samples never refuse
ideas, refinements or planning workers. Validation, row versions, active-request
exclusion, model budgets and actual SQLite/OS write failures still apply.

## Human conversation

`create_human_idea` validates 1–8,000 characters and persists an idempotent command
receipt, open thread, human message and pending request in one transaction.
`continue_human_thread` requires the current row version and an open thread;
it appends a message and new IntakeRequest. A thread cannot have overlapping
active Intake requests.

The request freezes the last included message ID. Conversation assembly is
bounded at 32,000 serialized characters; oversize input fails visibly rather
than silently truncating. A previous brief is provided to Gemini, and trend
refinement includes the original Detection evidence without recursively nesting
earlier conversations.

Intake uses `workflow_gemini_intake_prompt_v3` and
`workflow_gemini_intake_result_v2`. It records supplied intent without choosing a treatment. It cannot select a domain, platform, account,
format or generate content. Returned `open_questions` persist the first focused
question and finish the request as `needs_clarification`, with no revision.
A human reply creates another request. Otherwise Intake validates and commits
all brief fields (sparse intent is valid):

| Field | Meaning |
| --- | --- |
| `editorial_goal`, `topic` | Explicit goal or null, and normalized subject |
| `coverage_kind`, `canonical_target` | Stable editorial subject |
| `revision_scope` | Scope of the requested revision |
| `audience`, `desired_outcome` | Exact supplied wording or null when unknown |
| `constraints` | Structured editorial constraints |
| `source_context` | Route-neutral context summary |
| `open_questions` | Empty on a completed brief |

The caller stamps `field_authority`: explicit human intent, unknown values,
normalized subject identity, system-default coverage category and model summary
remain distinguishable. Unsupported optional intent is normalized to null and
unsupported constraint values are removed by exact source-wording checks.
New human coverage_kind defaults to `subject`; refinements preserve the existing
identity. Explicit bounded slide requests use `constraints.content_slide_count`.
No question is forced merely because a topic is short. Summaries are not evidence.
The brief and source snapshot are immutable. Refinement creates a numbered child
revision; old decisions and jobs remain intact. Refinement cannot silently
change coverage identity. A materially different subject needs a new thread.

## Identity and collision

`coverage_normalization_v2` serializes kind (casefolded/trimmed) and target
(casefolded, trimmed, collapsed whitespace). It is a string identity, not
semantic equivalence. Pipeline/account/style do not participate.

If human Intake discovers another thread already owns this coverage, it writes
a visible message identifying that thread and closes the duplicate without a
revision. Detection separately fences selected event identities across Scout
evaluations. Automatic cross-thread semantic coverage reuse is not implemented.

## Frozen catalog

Setup registers three domains before any handoff. The shared catalog reader
provides each domain's human name, purpose, scope, exclusions, enabled/generation-ready state and eligible output
bindings. Development bindings are synthetic Instagram fixtures, not verified
social accounts. The preserved inactive delivery catalog checks readiness from persisted facts.

Each DeterminationRequest freezes its brief, evidence and catalog at creation.
A deterministic model view takes the latest observation per lexical-cluster,
source and scoring-credit state, up to 24 representatives. It discloses total,
included and omitted counts so repeated polls are not mistaken for independent
sources. Full observations remain in the frozen snapshot and dashboard;
only the model input is compacted. Trend refinement uses the same projection.
A SQL immutability trigger prevents input/revision/fingerprint updates. Later
registration, activation or readiness changes cannot rewrite an existing
request. A new human revision is required to request a new planning decision
against current capabilities.

## Determination

Gemini evaluates every entry in the frozen `DOMAIN_CATALOG` independently.
The prompt and response cardinality/IDs derive from that catalog, not a separate
list in generic prose. Active domain registration still contains the three current domains. Selected
domains must offer substantively distinct reader value; skipping is normal.
Disabled/unready domains and outputs cannot be selected.

Response schema and semantic validation are owned by
`src/workflow/gemini_determination.py`. Required aggregate fields are
`outcome`, `opportunity_value`, `rationale`, `warnings` and exactly three routes.
Each route has a registered `pipeline_id`, `disposition` (`selected`,
`skipped`, `blocked`), `fit`, nonempty `reason`, and outputs.

Determination decides domain eligibility, not a strategic angle. Outputs must
match ready entries from the frozen catalog, exactly one Instagram binding for
each selected route. Its structured result is
`workflow_gemini_determination_result_v2`, with `determination_policy_v2` and
`workflow_gemini_determination_prompt_v4`.

- `accepted`: at least one selected route.
- `blocked`: no selection and at least one operationally blocked route.
- `not_recommended`: no selected or blocked route.

Validation failure fails the claim and writes the model-attempt outcome; it
does not persist a partial decision. Finalization atomically writes the decision,
three route assessments, and one pending EditorialPlanRun per selected route.
No output binding means no selected route.

## Editorial Planning

`src/workflow/editorial_planning.py` owns the closed `editorial_plan_v2`
contract, `editorial_input_v1` input and `editorial_planner_v2` model prompt.
Determination asks whether to cover a brief; Editorial Planning chooses the
story treatment; canonical generation writes it. Visual planning remains downstream.

Lanes are closed: `trend` is substantially driven by dated attention/events (this pass requires
frozen evidence provenance and at least one selected-candidate reference);
`evergreen` has lasting usefulness; `series` is an intentional recurring format;
`experiment` tests a materially different editorial strategy. Unusual content or
another visual archetype does not imply an experiment. Optional `series_key` is
allowed only for series; optional `experiment_key` and required experiment intention
are allowed only for experiments. No scheduling or feedback machinery is composed.

Each plan has 2–4 unique candidate IDs/angles and one selected candidate ID.
Candidates contain domain strategy, reader promise, relevance, 1–8 must-cover points,
evidence references/requirements and qualification requirements. Plan-level fields
include domain, lane, audience intent, nullable evergreen why-now, selection rationale and structured
reasoning for domain fit, usefulness, evidence strength, timeliness, novelty and
explanatory potential. The selected candidate owns the selected angle/promise/points;
these are not duplicated as independently editable fields.

The caller stamps brief/route IDs, planner/schema version, input hash and frozen
history into the immutable artifact. The latest 12 committed same-domain plans,
ordered by plan ID descending, are frozen at Determination handoff, with IDs,
input fingerprints, lanes, angles, strategies and promises. This includes planned
content even before generation. One destination per domain makes this history
appropriate to the active system. Simultaneous pending plans cannot see each other's
future choices. No vectors or unbounded queries are used. Each candidate supplies bounded
0–4 relevance and evidence scores. Selection maximizes three times relevance plus
evidence minus treatment recency penalty (two for a matching most-recent-three
plan, otherwise one per match, capped at two). Candidate order breaks ties.
The validator enforces selection; relevance can outweigh repetition. The prompt
requires comparative novelty reasoning. This is a bounded diversification policy,
not an objective evaluation of model-assigned relevance. Planning obligations
request what to explain without embedding unsupported answers. Evidence requirements
are actual support conditions and may be empty; evergreen why-now may be null.

Inputs retain frozen brief constraints and source conversation, source fingerprint,
as-of UTC timestamp, Detection evidence and representative-selection counts.
Models receive only repository evidence; IDs and dates are never model-generated.
Human editorial intention is a strong constraint, subject to remit and evidence.
No platform/renderer fields occur in the plan. Output bindings remain input/handoff
provenance, not editorial model decisions.

Recursive closed validation enforces enums, bounds, unique selection, reference
membership, domain strategies, lane metadata and required qualification codes.
English requires usage context and no invented etymology/cultural claims; AI/Tech
requires source backing, dated context, scope, limitations and provider-claim
separation; Psychology requires observation/inference separation, alternatives,
uncertainty and non-diagnostic framing. These structural checks do not prove
semantic compliance or factual entailment; human review remains necessary.

One bounded Gemini call uses the existing invocation/budget ledger and transport,
without research or hidden repair. Insufficient evidence must lead to a supported
alternative; an invalid/unsupported result fails the run visibly. There is no
fallback plan on paid failure. Deterministic mode has an explicit offline fixture
planner. Input over the shared 32,000-character guard fails before invocation.
Planning consumes the daily budget before a job exists and ignores storage admission.

A live fenced claim atomically commits plan, ContentJob and pending GenerationRun.
Failure, cancellation or stale finalization creates no partial downstream work.
SQL uniqueness prevents duplicate jobs, and external invocation history prevents
blind replay after expiry. Fresh schema-16 databases are required; no migration
or reset is performed. [Data model](data-model.md) owns SQL lineage.

## Runtime and review

`run_workflow.py --gemini --planning-only --poll` runs Intake, Determination and Editorial Planning
plus storage monitoring. No generation/rendering/posting worker is composed.
The default non-Gemini policies are deterministic fixtures.

Each Gemini call has a bounded phase allowance and invocation ledger entry;
configured prices and daily/job limits are required by the real runner.
Unknown or failed paid invocations are not automatically replayed. Polling
reports clarification, failure and retry-wait states distinctly from idle.
The dashboard displays conversation, brief, all routes, angles, jobs and model
usage. Humans judge editorial quality; structural validity does not prove it.

See [runtime](runtime.md), [dashboard](dashboard.md) and
[reliability](reliability.md) for leases, visibility and external-call safety.
