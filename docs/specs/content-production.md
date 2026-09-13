# Canonical Content and Production Specification

**Document role:** Tier 2 target production contract.
**Owner:** Domain generation, canonical content, output adaptation, bounded
fan-out, checkpoints, and production admission.
**Read with:** [Data model](data-model.md), [Intake and Determination](idea-intake-and-determination.md),
[Domain pipelines](../pipelines/domains.md), [Platform outputs](platform-outputs.md),
[Reliability](reliability.md), and [Runtime](runtime.md).

## Boundary and lineage

```text
selected DeterminationRoute (domain + angle)
  → immutable ContentJob + first GenerationRun
  → Pipeline Runner invokes domain strategy
  → immutable CanonicalContent + frozen OutputRequests + AdaptationRuns
  → Adaptation Worker invokes platform-output strategy
  → immutable ContentPackage + first RenderRun
  → Visual Renderer → exact assets + independent ReviewRequest
```

Workers communicate through SQLite only. Domain strategies never call output
adapters, renderers, or social APIs. The Adaptation Worker never calls the
renderer. Output adaptation is a creative stage; delivery adaptation in the
Posting Agent is a different, noncreative stage.

## Canonical content — `canonical_content_v1`

One selected domain/angle job produces at most one successful canonical object.
The object has a common, versioned envelope and a discriminated domain extension:

| Field group | Required meaning |
| --- | --- |
| Lineage | Content job, generation run, brief revision, coverage identity, nullable trend/opportunity reference for human ideas, pipeline ID/version |
| Angle | Frozen angle identity, target, audience, thesis, expected reader value; generation cannot replace it |
| Content | Hook, context, ordered key points, ordered examples, conclusion/takeaway, optional CTA |
| Claims and sources | Stable claim IDs, source/reference IDs and versions, as-of context, source type, factual/hypothetical/inference labels, qualification and attribution requirements |
| Domain payload | Exactly the matching domain extension from the domain catalog |
| Integrity | Schema/prompt/model policy versions, canonical serialized hash, validation evidence |

No account, platform caption, hashtag policy, thread segmentation, slide layout,
HTML/CSS, pixel geometry, or renderer choice belongs in canonical content.
Human-origin content may have no trend, but must retain its submitted context
and evidence. Sources are bounded verified inputs; they are not raw provider
responses or invitations for the model to fetch a URL.

Claims must reference evidence actually frozen in the job, or be explicitly
labeled generated examples/qualified inference. A structural validator checks
references and the domain schema; bounded model-assisted validation may check
meaning, naturalness, and support, but cannot fetch facts or silently repair.
Validation never declares an unsupported factual claim verified merely because
a model repeated it. Unsupported required claims fail before canonical commit.

**Current implementation:** `GeminiPipelineRunner` claims the existing v2
GenerationRun, audits one model invocation, and validates a closed common body
plus the matching extension for each of the five registered domains. Claims are
limited to `source_bound_fact`, `qualified_inference`, or `generated_example`;
source-bound references must exist in the frozen job snapshot. Successful commit
creates the frozen Instagram/X OutputRequests atomically. Synthetic mode is
review-only. In v4 production mode, the same call must first reserve its priced
worst case under daily and per-job limits. The structural evidence check is
implemented; deeper reference-quality validation, canonical reuse, and the
execution/capacity reservations below are not.

The shared client projects array cardinalities into provider-facing descriptions
to avoid Vertex constrained-decoder complexity errors. The full local validators
still reject out-of-range lists; see the
[Gemini boundary](reliability.md#configuration-and-gemini-accounting).

## Immutable job and output plan

Determination freezes the domain/angle recipe and a bounded list of enabled
output bindings. Each binding identifies platform, configured account,
format, output-contract version, renderer compatibility, and policy versions.
The initial fan-out is at most one Instagram and one X output per selected
domain (at most ten packages per brief revision), not every account in a catalog.
X single post and X thread are mutually exclusive formats for that binding.

Changing a platform/account does not change canonical content identity. It does
change output identity and needs an explicitly authorized new output plan.
Phase 1 does not automatically backfill newly configured destinations. A later
human revision may reuse an existing canonical object only when its domain,
angle, evidence, and creative input fingerprint are unchanged and an immutable
reuse link records that choice; it must not falsely attribute old content to a
new generation call. Creative/evidence changes require a new canonical job.

For explicitly scoped output rework with unchanged canonical input,
Determination finalization atomically persists the reuse link and only the new
OutputRequest/initial AdaptationRun, starting `waiting_capacity`. Its model calls
retain the original ContentJob budget owner and prior spend; reuse never starts
a fresh generation budget. An unchanged existing output request is linked,
not duplicated. A budget exhausted by earlier work remains exhausted until a
separately approved policy/recovery design permits more spending.

Generation success is one fenced transaction: persist the unique canonical
object, complete the run, create every frozen OutputRequest and its initial
AdaptationRun, and release the generation execution slot. It creates no render
or review directly. Database uniqueness makes re-finalization idempotent.

## Output adaptation — `output_adaptation_v1`

The adapter reads the immutable canonical object and one OutputRequest. It may
select/compress/reorder supported points, write native connective copy and
metadata, and choose compatible visual templates. It may not change the angle,
invent facts, drop necessary qualifications, alter source meaning, or fetch new
evidence. A need for new content returns a typed failure requiring a revision.

Platform-specific copy, caption/tags/hashtags, alt text, ordered thread text,
claim mappings, selected profiles, and structured visual bindings are all frozen
in the package before rendering. The worker may use bounded Gemini adaptation
under its own recorded phase; deterministic serializers/validators enforce the
final format. A failure on X does not rerun domain generation or invalidate a
completed Instagram sibling.

Persist validated adapted body/units and their hash before metadata or a bounded
repair phase. A metadata retry consumes that checkpoint across process restart
and cannot rewrite its content. Adaptation success atomically completes the run,
inserts one ContentPackage per OutputRequest, and creates its first RenderRun.
After package commit, creative change requires a new human revision/output
request, never in-place repair. Rendering retries reuse the exact package.

A metadata validation or generation failure does not discard or regenerate
the canonical content. The adaptation run may retry its own bounded metadata
attempts using the already-checkpointed adapted body. Canonical content is
committed before any adaptation begins.

**Current implementation:** `GeminiAdaptationWorker` validates either an
Instagram 5–8-unit carousel or one X post/card, normalizes tags/hashtags, maps
every canonical claim, freezes a visual specification, and creates one
independent package/render run. Synthetic mode remains review-only. Production
mode reserves each call, persists the validated body and metadata independently,
and permits one metadata-only retry from the body checkpoint without rewriting
it. Failure is branch-local and never changes or regenerates canonical content.

Adaptation prompt v2 states the existing local copy/CTA/tag/alt-text limits
explicitly; in particular an Instagram CTA is optional and capped at 12 words.
The wire schema also constrains that CTA to at most 12 whitespace-separated
words and 120 characters. Gemini 3 adaptation uses the bounded thinking and
temperature policy in [Configuration](configuration.md); local validation
remains authoritative and failed output is never silently repaired or published.
The initial prompt omitted that limit and a live response failed validation.
This changes model guidance, not the persisted package limits or review rules.

## Admission and model spending

**Implementation split:** v4 implements `gemini_budget_v1` reservations and
settlement. Positive price, warning, daily-hard, and per-job-hard values come
from validated production environment settings; each phase also has a positive
input/output token maximum. Reservation occurs before the provider call, daily
hard-limit exhaustion defers the claim to the next UTC day, and job-cap
exhaustion fails it. The capacity/slot allocator described next is still target
design and is not an eligibility condition in the current runner.

`production_admission_v2` separates bounded execution from unreviewed-output
capacity. The proposed initial execution limit is one active GenerationRun and
one active AdaptationRun system-wide. Each configured destination has two
unreviewed-output slots. These are internal cost/backlog limits, not API quotas.

Before admitting canonical generation, reserve one output slot for each frozen
destination plus the generation slot atomically, in deterministic binding order.
If any required slot is unavailable, keep the run `waiting_capacity`; make no
model call and hold no partial reservations. Human-origin work precedes trend
work, then oldest creation time/ID. Reserved downstream slots survive generation
success and are transferred to their OutputRequests. Initial AdaptationRuns are `waiting_capacity` until the gate reserves their
adaptation execution slot; generation-created runs already hold the transferred
destination reservation. Output-local rework acquires its own destination slot
at this gate. The Adaptation Worker
claims only a run with a destination slot and an available adaptation execution
slot. No output duplicates a reservation on retry/restart.

Release each destination slot only on its branch's generation/adaptation/render
failure, cancellation, or terminal review outcome. A fresh review/recovery must
reacquire a slot. A canonical failure releases all its unused output slots.
Sibling terminal outcomes release only their own slots. Adaptation success
releases its execution slot while retaining the destination slot through review;
failed/cancelled execution releases its execution slot as well. Safe retry wait
retains its reservations; terminal recovery must reacquire them. All slot changes are
audited SQLite transactions. Slots are never released merely by browser close
or a temporary worker outage. Leases and cost-uncertainty rules still apply.

`phase1_model_policy_v1` proposes at most two canonical drafting attempts and
two adaptation drafting attempts per destination, plus one bounded validation
call per draft and up to two metadata attempts per destination. Every call,
including validation, repair, rejected output, and recovery, counts against the
same domain ContentJob's initial 30,000-token and USD 0.25 caps across generation
and all its adaptations. These conservative inherited caps must be priced and
checked against frozen per-phase maxima before activation; they are ceilings,
not a guarantee every configured phase fits. Never silently raise them or split
adaptation into a fresh budget to evade the cap.

The shared daily budget in [Reliability](reliability.md) also applies to Intake,
Determination, generation, and adaptation across all five domains. Missing
model/price/token policies block calls. A stale started call retains an uncertain
reservation and cannot be automatically repeated. Waiting work spends nothing.
Persist stage-level usage so reuse savings and actual fan-out cost are visible.

## Revisions, cancellation, and duplicates

Cooldown expiry is not duplicate permission. The domain-angle coverage guard
and immutable creative fingerprint are checked before reserving model cost;
identical creative must reuse the existing canonical record or explicitly skip.
An output fingerprint and destination publication guard separately prevent
repeat adaptation and accidental republishing. The Data Model also defines a
final-public-payload duplicate fingerprint independent of new audit IDs; a new
package or revision alone cannot bypass confirmed/uncertain publication history. Explicit rework can create a new
revision but does not erase or bypass a confirmed/uncertain publication.

A platform-local change request records the exact reviewed OutputRequest as
its scope. Reuse canonical content when unchanged and create a replacement only
for that branch; leave siblings intact. A domain-level creative change scopes
the new revision to that domain; changing the common brief/evidence may require
rerouting all domains. Intake records the scope explicitly before paid work.
New revisions never silently cancel approved or in-flight sibling deliveries.

Thread cancellation fences every uncompleted branch and prevents new handoffs.
Public or possibly public work remains in audit. Canonical content and packages
are immutable and retained even when their branches are rejected/cancelled.

## Acceptance and implementation gate

Boundary tests must cover zero/one/many routes, one canonical record serving two
outputs, no second canonical call after adaptation failure, atomic full fan-out,
stale-claim rejection, restart checkpoints, uncertain model cost, cap exhaustion,
capacity acquisition/release, scoped rework, duplicate content across revisions,
and independent approval/cancellation of sibling destinations.

This remains the accepted production target. The v4 implementation completes
the bounded paid-call, checkpoint, render, exact-approval, and single-post
delivery slice while keeping closed in-code Gemini schemas over the v2 creative
records. It does not complete capacity slots, cross-revision reuse, recurrence,
or full domain/reference validation. Those additions need forward contracts and
fixtures; existing migration bytes must not be edited. The
[target plan](../plans/target-implementation.md) tracks that remaining work.
