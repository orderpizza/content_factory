# Idea Intake and Determination Specification

**Document role:** Tier 2 current planning contract.
**Owner:** Human conversation, immutable briefs, five-domain decisions and job creation.

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

Gemini Intake is route-neutral. It cannot select a domain, platform, account,
format or generate content. Returned `open_questions` persist the first focused
question and finish the request as `needs_clarification`, with no revision.
A human reply creates another request. Otherwise Intake validates and commits
all brief fields:

| Field | Meaning |
| --- | --- |
| `editorial_goal`, `topic` | What to explain and why |
| `coverage_kind`, `canonical_target` | Stable editorial subject |
| `revision_scope` | Scope of the requested revision |
| `audience`, `desired_outcome` | Who benefits and what they should learn/do |
| `constraints` | Structured editorial constraints |
| `source_context` | Route-neutral context summary |
| `open_questions` | Empty on a completed brief |

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

Setup registers five domains before any handoff. The shared catalog reader
provides each domain's remit, enabled/generation-ready state and eligible output
bindings. Development bindings are synthetic Instagram/X fixtures, not verified
social accounts. Production catalog readiness is checked from persisted facts.

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

Gemini evaluates `english`, `ai_tools`, `personal_finance`,
`business_side_hustle` and `psychology_behavior` independently. Selected
domains must offer substantively distinct reader value; skipping is normal.
Disabled/unready domains and outputs cannot be selected.

Response schema and semantic validation are owned by
`src/workflow/gemini_determination.py`. Required aggregate fields are
`outcome`, `opportunity_value`, `rationale`, `warnings` and exactly five routes.
Each route has a registered `pipeline_id`, `disposition` (`selected`,
`skipped`, `blocked`), `fit`, nonempty `reason`, optional angle and outputs.

A selected angle requires `angle_kind`, `canonical_target`, `audience`,
`thesis` and `reader_value`. Outputs must match ready entries from the frozen
catalog, at most one per platform and two total.

- `accepted`: at least one selected route.
- `blocked`: no selection and at least one operationally blocked route.
- `not_recommended`: no selected or blocked route.

Validation failure fails the claim and writes the model-attempt outcome; it
does not persist a partial decision. Finalization atomically writes the decision,
five route assessments, and one ContentJob + pending GenerationRun per selected
route. The job freezes its domain/angle recipe and output plan. No output
binding means no selected job.

## Runtime and review

`run_workflow.py --gemini --planning-only --poll` runs Intake and Determination
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
