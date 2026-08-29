# Detection Specification

**Document role:** Tier 2 target design contract. It defines required behavior;
verify implementation conformance from code and tests.
**Owner:** Trend Scout, source adapters, aggregation, scoring, shortlist
selection, candidate evidence, and automatic recurrence.
**Read this for:** Any detection source, signal, algorithm, score, threshold,
candidate lifecycle, shortlist, evidence, or source-health change. Read
[the system guide](../system.md) first and [the data model](data-model.md) for
the exact persisted records and constraints.

## Scope and boundary

Detection finds and measures system-wide, externally observable attention. It
is deterministic, explainable, and LLM-free. It does not generate content,
choose creative, select a pipeline, or call a downstream component.

The database is the durable handoff boundary, not a scoring component. The
Trend Detector calculates scores from observations and persists all resulting
`TrendCandidate` records. The Trend Shortlist then reads those persisted
candidates and, for selected work, atomically creates a source-backed
`ContentThread` and pending `IntakeRequest`. The shared Idea Intake flow claims
that request and freezes the thread's first `BriefRevision` before it creates a
`DeterminationRequest`.

```text
Source adapters
  → observations
  → Trend Scout / Detector: normalize, cluster, score
  → SQLite: every TrendCandidate and evidence snapshot
  → Trend Shortlist: eligibility, threshold, budget selection
  → SQLite: ContentThread + IntakeRequest only for selected candidates
  → Idea Intake claims request and freezes BriefRevision
  → SQLite: DeterminationRequest
  → Determination
```

An unselected candidate remains visible in SQLite and the dashboard. It is not
lost and it has not been handed to Determination.

## Detection lifecycle

1. Source adapters collect observations with source-instance identity,
   measurement window, collection time, raw unit, and safe provenance.
2. The detector canonicalizes and clusters related observations, retaining the
   exact cluster membership and source evidence.
3. The detector normalizes each source in its own unit, calculates a versioned
   score, and persists every candidate with its score breakdown and evidence
   fingerprint.
4. After the complete scored set is durable, the shortlist applies the active
   deterministic policy to persisted candidates.
5. In one transaction, the shortlist marks the selection and creates one
   `ContentThread` with `origin=trend` plus its pending `IntakeRequest`. The
   records retain the candidate ID, producing detection run, evidence
   fingerprint, and exact evidence snapshot.
6. Idea Intake claims that request and freezes a source-backed Revision 1. Its
   `source_snapshot_json` carries the selected candidate evidence and producing
   detection run; Determination never performs a later topic-string lookup.

No source, detector, or shortlist process calls Idea Intake or Determination
directly.

## Initial system-wide source portfolio

Detection sources are system-wide attention signals. They are not owned by O2
or any other content pipeline; Determination decides which enabled pipeline, if
any, can use a selected opportunity.

The initially enabled source kinds are:

| Source kind / stable ID | Scope and measurement | Collection policy | Required provenance and guardrails |
| --- | --- | --- | --- |
| `rss_atom_feed_v1` | An operator-approved RSS or Atom feed. One source instance is one feed URL; the raw measure is unique published feed items that join a canonical candidate cluster during a trailing 24-hour UTC window. | Poll each enabled feed every 15 minutes. De-duplicate by feed GUID, or normalized link/title when GUID is absent. | Store source-instance ID, feed URL, item GUID/link, published/collected time, title, and raw item count. Only allow HTTPS feeds with an explicit display name and topic/scope note. A feed is enabled only through the persisted source registry. |
| `wikimedia_enwiki_pageviews_v1` | The daily most-viewed English Wikipedia articles (`en.wikipedia.org`, all access, all agents) for the preceding completed UTC day. The raw measure is the reported daily view count and rank. | Fetch once after the provider's daily data is available; subsequent Scout polls reuse the same completed-day snapshot. | Store article identifier/title, report date, rank, view count, endpoint/version, and collection time. Exclude non-content/navigation entries and duplicate article identities before clustering. |

The Wikimedia Analytics API provides the project pageview/top-pages data used by
the second source. This provider fact was verified on 2026-08-29; endpoint,
availability, and attribution requirements must be rechecked before a provider
change. See the official [Wikimedia Analytics API project-metrics reference](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/examples/project-metrics.html).

`rss_atom_feed_v1` is an allowlisted source kind, not a hidden hard-coded feed
list. Individual feeds are source-instance configuration and may be enabled or
disabled without changing a detection algorithm. No other source kind is
enabled until this specification is updated and its source instance is added to
the registry.

### Source-instance registry

Every enabled external input has one persisted `DetectionSourceInstance` record
with a stable ID, source kind/version, display name, endpoint/feed URL,
topic/scope note, enabled state, expected cadence and measurement window,
static trust weight, configuration fingerprint, and audit timestamps. It never
stores credentials. A run freezes the enabled source-instance configuration it
used so historical observations remain interpretable.

Initial static trust weight is `1.00` for both source kinds. This is not an
editorial-quality assertion: source-health reliability is calculated separately
from successful collection, timeliness, and completeness. A future change to a
source's static trust weight must be versioned and justified here.

## Scoring model — `attention_v1`

The score measures externally observable attention only. It does not decide
whether a topic is useful, safe, factual, or suitable for any pipeline; those
are Determination responsibilities.

All calculations use completed 24-hour UTC windows. The Scout may run every 15
minutes, but it never treats repeated collection of the same unchanged
Wikimedia daily report as new attention. RSS activity is aggregated over the
trailing 24-hour window after feed-item de-duplication.

For each candidate and source kind `s`:

- `A_s` is current normalized activity: distinct matching feed instances for
  RSS/Atom, or reported page views for Wikimedia.
- `B_s` is the median `A_s` over the preceding 14 completed equivalent windows,
  excluding unavailable/degraded windows. History is **ready** only after at
  least seven valid windows.
- `G_s` is source-kind momentum:
  `clamp(log2((A_s + 1) / (B_s + 1)) / 2, 0, 1)`. A fourfold-or-greater lift
  therefore has momentum `1.0`.
- `P_s` is current-window prominence, normalized to `[0, 1]` from the source
  kind's ranked candidate population. For RSS it ranks the number of distinct
  matching feeds; for Wikimedia it uses the provider article rank/view count.
- `R_s` is source reliability: static trust weight multiplied by source health
  (`1.0` healthy, `0.5` degraded, excluded when unavailable/failed).

When a source kind has insufficient history, its provisional `G_s` is
`0.5 × P_s` and is explicitly labeled **bootstrap**, never represented as
observed growth. This allows an early multi-source event to surface while
preventing a single un-baselined source from being selected by itself.

Candidate-level components are all in `[0, 1]`:

| Component | Definition | Weight |
| --- | --- | --- |
| Momentum | Reliability-weighted mean of contributing `G_s`. | 0.30 |
| Prominence | Reliability-weighted mean of contributing `P_s`. | 0.20 |
| Breadth | `min(1, independent enabled source instances / 3)`. | 0.20 |
| Persistence | `min(1, distinct completed windows observed in the last 72 hours / 3)`. | 0.10 |
| Freshness | `clamp(1 - age_hours / 48, 0, 1)` using the most recent source evidence. | 0.10 |
| Reliability | Reliability-weighted mean `R_s` for contributing sources. | 0.10 |

`attention_v1_score` is the weighted sum of those components, rounded to four
decimals. The persisted score breakdown includes each source-kind input,
history readiness/bootstrap state, every component, formula version, and final
score. No database query or dashboard calculation is allowed to alter it.

## Algorithm and evidence principles

- Normalize heterogeneous inputs before combining them. RSS item counts and
  Wikimedia page views are not directly comparable.
- Score momentum, prominence, corroboration breadth, persistence, freshness,
  and source reliability as distinct explainable factors. Persist score and
  canonicalization versions.
- Define first-observation behavior and deterministic tie-breakers:
  corroboration breadth, prominence, freshness, then stable candidate ID.
- Preserve source-instance identity, measurement windows, latency, fallback or
  degradation, and structured collection errors. A source’s stale/degraded
  state is visible and can be deterministically penalized or excluded.
- Retention is not selection: persist the complete scored set before applying
  any threshold or budget.
- Change an algorithm through versioned configuration and migration-aware
  records so historical candidates remain interpretable.

The detailed candidate/evidence fields, indexes, and uniqueness constraints
belong in [the data model](data-model.md). The dashboard presentation and
freshness rules belong in [the dashboard specification](dashboard.md).

## Shortlist policy — `shortlist_v1`

The shortlist is a separate deterministic policy, not an implication of a
candidate's score. It evaluates persisted candidates against the configured
eligibility rules, minimum score, and budget after the complete scored set is
durable.

An automatic candidate is eligible for its **initial selection** only when all
of these are true:

- `attention_v1_score >= 0.6000`;
- candidate reliability is at least `0.70`;
- it has either one history-ready contributing source kind or evidence from at
  least two independent enabled source instances;
- it has no existing thread with the same coverage identity; and
- it is within the global system-wide selection budget: at most two newly
  selected candidates in a rolling six hours and at most six in a rolling 24
  hours.

Eligible candidates are ordered by final score descending, then breadth,
prominence, freshness, and stable candidate ID. The shortlist selects only as
many candidates as remaining budget permits. It records the policy version,
eligibility result/reason, rank, selected time, and selected thread ID on the
candidate audit trail. Candidates that meet the score threshold but lose to the
budget remain persisted and visible as `deferred_by_budget`; they are
re-evaluated on later runs while their evidence remains fresh.

- A candidate with an `accepted` Determination decision is consumed for
  automatic routing permanently; time passing alone does not reconsider it.
- A candidate with a `not_recommended` determination outcome may re-enter only
  after three days **and** a material, deterministic change to its evidence
  fingerprint under a versioned materiality comparator. The shortlist appends
  a `ThreadEvidenceEvent` and pending `IntakeRequest` to its existing trend
  thread. Idea Intake may then create an `evidence_refresh` Brief Revision; no
  duplicate thread is created.
- Worker recovery resumes the same persisted selection/thread; it does not
  create a replacement from unchanged evidence.
- A human may continue an existing content thread and make an intentional new
  revision. That is auditable rework, not automatic trend duplication.
- Future recurring coverage needs a separately documented editorial
  freshness/version policy; it must not weaken the rules above implicitly.

Evidence identity, coverage identity, content identity, and publication
identity solve different duplication problems. A single hash must not be
reused as a shortcut for all of them.

## Change and acceptance requirements

Before changing a detection algorithm or source, document the score/version,
input units, normalization, selection impact, and rollout/migration treatment
in this specification. Add boundary tests for:

- source registry/allowlist, normalization, source degradation, and retained
  provenance;
- canonicalization, clustering, score breakdown, bootstrap behavior, and
  deterministic ties;
- persistence of every scored candidate before selection;
- shortlist threshold/budget behavior and source-backed thread creation; and
- recurrence, cooldown, material evidence change, and idempotent recovery.

Detection quality is observed through the dashboard's detection view; it must
show source-instance configuration/health, evidence, source-kind score inputs,
formula/policy versions, selection outcome, and the resulting trend thread and
revision where one exists.
