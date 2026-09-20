# Detection Specification

**Document role:** Tier 2 active Detection contract.
**Contract owner:** Detection subsystem.
**Owned components and responsibilities:** source adapters, collection,
normalization, lexical clustering, semantic event resolution, scoring, shortlist selection, cluster evidence,
and immutable selected-event handoffs.
**Read this for:** Any detection source, signal, algorithm, score, threshold,
cluster lifecycle, shortlist, evidence, or source-health change. Read
[the system guide](../system.md) first and [the data model](data-model.md) for
the exact persisted records and constraints.

## Purpose and boundary

Detection measures externally observable attention from configured sources. The
active implementation uses local embedding inference and deterministic scoring
over frozen resolved membership. It is LLM-free. It does not make
editorial judgments, choose a domain or angle, generate content, or call a
downstream worker. Its output is a persisted handoff for Determination when a
cluster passes the shortlist policy.

Detection has two active workers:

- `DetectionCollector` collects provider data and persists source evidence.
- `DetectionScout` evaluates persisted evidence, writes cluster records, and
  creates the direct trend handoff when a cluster is selected.

## Vocabulary

- **Source / Feed:** one configured external stream.
- **Raw Feed Item:** one normalized item observation; repeated measurements may
  share a provider identity. The persisted record is `trend_observations`.
- **Cluster:** related Raw Feed Items grouped by deterministic lexical
  canonicalization and conservative semantic event resolution. A scored Cluster
  has immutable evaluation snapshots and a mutable Detection lifecycle projection.
- **Hacker News provider score:** the provider's vote score `q`, never the final
  Detection decision score.
- **Source activity:** the source-specific measurement stored on an observation.
  HN observations store the provider vote score. Scoring derives its window-level
  attention input `A_s` from that score and provider rank using the formula below.
  Neither the raw vote count nor `A_s` is the final Detection attention score.
- **Semantic similarity:** MiniLM cosine evidence for event linking, not attention.
- **Detection attention score:** the frozen cluster-level evidence measurement.
- **Detection Selection:** the separate complete threshold/reliability/history/
  corroboration/identity/budget policy.
- **Opportunity:** a cluster that passes Detection Selection and receives a
  Determination handoff, not every scored cluster.
- **Determination Decision / ContentJob:** downstream editorial domain/angle
  evaluation / persisted production request for a selected route.

Persisted identifiers such as `trend_candidates`, `score`, and
`opportunity_identity` remain implementation keys; the latter can reserve an
identity before selection and does not imply that a handoff exists.

`trend_candidates` is the implementation record for a Cluster's Detection
lifecycle. It is not a separate user-facing concept.

## Status ownership

| Layer | States and meaning |
| --- | --- |
| Collection attempt | `pending`, `claimed`, `running`, `retry_wait`, `completed`, `failed`: one Source / Feed fetching operation. |
| Source health | `healthy`, `degraded`, `unavailable`, `quota_limited`, `failed`: whether usable recent evidence exists. Frozen Scout input separately records `current` or `reused` evidence usage; neither is a Selection outcome. |
| Raw Feed Item | Immutable normalized observation. It has no Detection Selection state; its source attempt and per-evaluation scoring credit are separately inspectable. |
| Cluster: `observed` | Scored but one or more complete Selection gates are not met. Reason explains why. |
| Cluster: `eligible` | Evidence gates passed; Selection has not committed a handoff. Usually an intermediate state within Scout's transaction. |
| Cluster: `deferred_by_budget` | Evidence gates passed, but no remaining global Selection capacity. Still a Cluster, not an Opportunity. |
| Cluster: `selected` | Complete Selection committed the trend ContentThread, initial source-backed BriefRevision and DeterminationRequest atomically. This is an Opportunity. |

The schema also allows `deferred_stale`, `rejected_cooldown`, `consumed` and
`reconsiderable` on the Cluster projection. No current Scout/Determination
transition writes those values; they are not Source or Raw Feed Item states and
are not offered as active dashboard filters. Processing an Opportunity does not
change `selected` to `consumed`: its Determination request status and decision
outcome describe processing. ContentJobs exist only for selected domain routes;
their latest GenerationRun provides production status, not publication status.

Storage samples are observability only for Detection. Collection, clustering,
scoring, Selection and handoff proceed regardless of sample age or free-space
classification; actual database/OS write errors still fail normally.

## Implementation map

The following table maps documentation terms to their implementation. “Code”
means a Python module or callable. “Record” means a durable SQLite row. An
in-memory value is only an implementation detail between two calls; the SQLite
records are the cross-worker interface.

| Element | Implementation | Role |
| --- | --- | --- |
| Source adapter | Code in `src/detection/adapters.py`, exposed through `collect_source()` | Reads one configured provider and returns normalized adapter data. |
| `CollectedItem`, `CollectionResult` | Python dataclasses in `src/detection/models.py` | In-memory adapter results passed to the Collector. |
| `DetectionCollector` | Class in `src/detection/collector.py`; entry point `run_due()` | Claims due source attempts and persists observations, item events, and source health. |
| Source collection attempt | SQLite record | One scheduled attempt for one source instance. |
| Trend observation | SQLite record | One measured source item with provenance and measurement window. |
| Trend | SQLite record | The normalized subject shared by matching observations. |
| `DetectionScout` | Class in `src/detection/scout.py`; entry point `run()` | Freezes collection inputs, clusters observations, computes scores, persists clusters, and applies shortlist rules. |
| Semantic resolver | `src/detection/semantic.py`; `scout_event_resolutions` record | Bounded local MiniLM comparisons, event gates, complete-link partition and immutable evidence before scoring. |
| Topic snapshot | SQLite record | Immutable score and evidence for one subject in one evaluation run. |
| Trend cluster | SQLite record in `trend_candidates` | The subject's current lifecycle state, rank, score, and selection status. |
| Shortlist | Policy implemented inside `DetectionScout` | Threshold, reliability, breadth, evidence recency, and selection-budget queue checks. |
| Trend handoff | `ContentThread`, `BriefRevision`, and `DeterminationRequest` rows | Direct persisted input for Determination after selection. |
| Human Intake handoff | `IntakeRequest` row | Separate path for human conversation; not created for detected trends. |

## Execution path

The active trend path is:

```text
provider response
  → source adapter (`collect_source`)
  → `CollectionResult` / `CollectedItem` in memory
  → `DetectionCollector.run_due()`
  → source collection attempt + trends + trend observations in SQLite
  → `DetectionScout.run()`
  → lexical clusters → local resolution → immutable resolved membership in SQLite
  → topic snapshots + trend clusters + cluster memberships in SQLite
  → if selected: ContentThread + BriefRevision + DeterminationRequest
  → DeterminationWorker.run_once() or GeminiDeterminationWorker.run_once()
  → determination decision/routes + ContentJob(s)
```

The arrows after collection represent SQLite handoffs. Determination does not
read raw provider responses or query by topic title; it consumes the frozen
`DeterminationRequest` created for the selected cluster.

The human-origin path is separate:

```text
dashboard human message
  → ContentThread + IntakeRequest
  → IdeaIntakeWorker.run_once() or GeminiIntakeWorker.run_once()
  → BriefRevision + DeterminationRequest
  → Determination
```

The same `ContentThread`, `BriefRevision`, and `DeterminationRequest` records
support both paths. The difference is whether the brief is created directly
from frozen detection evidence or interpreted from human conversation.

## Evaluation and selection lifecycle

1. Source adapters collect observations with source-instance identity,
   measurement window, collection time, raw unit, and safe provenance.
2. The Scout freezes the completed collection attempts used for an evaluation,
   forms lexical clusters, resolves plausible events locally, and freezes the
   exact resolved membership and decision evidence before scoring.
3. It normalizes each source in its own unit, calculates a versioned attention
   score, and persists every cluster with its score breakdown and evidence
   fingerprint.
4. After the complete scored set is durable, the shortlist applies the active
   deterministic policy to persisted clusters.
5. In one transaction, the shortlist marks each selection and creates one seed
   `ContentThread` with `origin=trend`, a source-backed `BriefRevision`, and its
   pending `DeterminationRequest`. The records retain the cluster ID,
   producing detection run, evidence fingerprint, and exact evidence snapshot.
6. Determination claims the request and evaluates the frozen brief and source
   evidence. It never performs a later topic-string lookup and does not require
   an `IntakeRequest` for a trend-origin thread.

An unselected cluster remains visible in SQLite and the dashboard. It is not
handed to Determination. Clusters that fail an eligibility gate remain
`observed` with an explicit reason; `eligible` means the cluster can enter the
selection-budget transaction. Detection writes the downstream request as a
SQLite handoff; it does not invoke Determination synchronously.

### Collection and evaluation boundary

Detection persists two different work records. A `SourceCollectionAttempt` is
one scheduled, claimable provider operation for exactly one enabled source
instance. It freezes the active source configuration/request parameters before
the call and finishes with immutable observations plus health evidence, or a
typed incomplete/failed result. Safe retry returns that same attempt to
`retry_wait`; it must not replace a completed response.

Every 15 minutes, `Trend Scout + Shortlist` creates one
`ScoutEvaluationRun` for the UTC evaluation slot and claims it separately. It
makes no provider call. At `input_frozen_at`, it links one explicit state for
every enabled source instance: latest complete attempt is `current` or
`reused`, otherwise `degraded`, `unavailable`, `failed`, or `quota_limited`,
with the supporting attempt/health row and reason. It also freezes an immutable
list of every completed collection attempt used in the current and baseline
windows; the latest-attempt summary alone is not treated as the scoring input.
It computes all clusters only from that frozen set. Completion atomically persists every score snapshot
and cluster, then performs any shortlist selection. A collection that
finishes later belongs to a later evaluation slot; it cannot silently alter
this evaluation's clusters or selection.

## Source portfolio

Detection sources are system-wide attention signals. They are not owned by O2
or any other content pipeline; Determination decides which enabled domain pipelines, if
any, can use a selected opportunity.

Source instances and resolver policies are immutable configuration from the active
non-secret configuration release. The Scout reads only that release; it never
adds, edits, enables, or disables a feed/API source itself. Each collection and
evaluation freezes the release fingerprint that supplied its source/scoring
policy. See the [Configuration control plane](configuration.md).

Supported source kinds are:

| Source kind / stable ID | Scope and measurement | Collection policy | Required provenance and guardrails |
| --- | --- | --- | --- |
| `publisher_feed_collector_v1` | An operator-approved publisher feed. One source instance is one exact feed URL, which declares either RSS or Atom as its delivery format; the collector does not combine both formats for one source. The raw measure is unique published feed items that join a canonical cluster during a trailing 24-hour UTC window. | Poll each enabled feed every 15 minutes. De-duplicate by feed GUID, or normalized link/title when GUID is absent. | Store source-instance ID, publisher/display name, feed URL, declared delivery format, item GUID/link, published/collected time, title, and raw item count. Only allow HTTPS feeds with an explicit coverage note. A feed is enabled only through the persisted source registry. |
| `wikimedia_enwiki_pageviews_v1` | The daily most-viewed English Wikipedia articles (`en.wikipedia.org`, all access, all agents) for the preceding completed UTC day. The raw measure is the reported daily view count and rank. | Fetch once after the provider's daily data is available; subsequent Scout polls reuse the same completed-day snapshot. | Store article identifier/title, report date, rank, view count, endpoint/version, and collection time. Exclude non-content/navigation entries and duplicate article identities before clustering. |
| `youtube_most_popular_v1` | The configured first 50 positions of the returned `mostPopular` video chart for one region across all categories. The initial instance is the US chart. The raw measure is chart rank plus returned video statistics at collection time; it is not search or keyword-trend data. | Poll every 30 minutes using exactly one `videos.list` request with `chart=mostPopular`, `regionCode=US`, `maxResults=50`, and `part=snippet,statistics`; omit `videoCategoryId` and `pageToken`. Enforce a local ceiling of 1,000 quota units per UTC day. Stop collection and record `quota_limited` once the ceiling is reached. | Store video ID, title, channel ID/title, published time, category, chart position, returned statistics, collection time, request parameters, and provider/API version. Never use `search.list`. |
| `hacker_news_top_stories_v1` | The configured first 100 positions of the published Hacker News Top Stories ID list and each listed story's current rank and score. The raw measure is story rank plus score at collection time. | Poll the Top Stories list every 30 minutes, retain its full-list hash/count, take positions 1–100, then fetch one detail record for every selected ID in that same attempt. | Store HN item ID, title, outbound URL when present, score, rank, author, provider time, collection time, and item type. Ignore deleted/dead/non-story entries for cluster creation but retain the collection diagnostic. |

The Wikimedia adapter uses project pageview/top-pages data. Recheck endpoint,
availability and attribution requirements before a provider change; see the
[Wikimedia project-metrics reference](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/examples/project-metrics.html).

The YouTube adapter uses the official [`videos.list` chart endpoint](https://developers.google.com/youtube/v3/docs/videos/list),
which documents `mostPopular`, `regionCode`, and its one-unit quota cost. The
local ceiling is a Content Factory safety limit, not a claim about a provider's
default quota; recheck the [YouTube quota documentation](https://developers.google.com/youtube/v3/getting-started)
before changing it. The Hacker News adapter uses the public
[Hacker News API](https://github.com/HackerNews/API) Top Stories list and item
records. These references describe interfaces, not live account or endpoint readiness.

`publisher_feed_collector_v1` is an allowlisted collector, not a hidden
hard-coded publisher list. RSS and Atom are standard delivery formats, not
sources: each configured publisher feed chooses the one format returned by its
official URL. Individual feeds are source-instance configuration and may be
enabled or disabled without changing a detection algorithm. No other source
kind is enabled until this specification is updated and its source instance is
added to the registry.

### Configured source instances

The configured publisher-feed coverage is deliberately narrow; it is not a
general-news sample.

| Source-instance ID | Provider and coverage | Interface | Policy |
| --- | --- | --- | --- |
| `nasa_recently_published_rss_v1` | NASA's recent web-content stream; not all science, space or general-news attention. | [NASA feed](https://www.nasa.gov/feed/) — configured as RSS 2.0. | Enabled; poll every 15 minutes; no credentials. Retain feed-supplied provenance/metadata, never scrape linked article bodies. |
| `wikimedia_enwiki_daily_v1` | English Wikipedia — completed daily Top Pageviews report. | Wikimedia Analytics API/data response. | **Configured state:** enabled; fetch once for each completed UTC day after availability. |
| `youtube_us_most_popular_v1` | YouTube — US `mostPopular` chart across all categories. It is the complete chart returned by the provider, not all videos published in the US. | YouTube Data API `videos.list`; JSON. | **Configured state:** disabled by default in development; enable with setup --include-youtube; poll every 30 minutes; 1,000 local quota-unit ceiling per UTC day. The data model permits further regional instances, but Korea is not enabled in the initial roster. |
| `hacker_news_top_stories_v1` | Hacker News — Top Stories ranking. It is the complete provider Top Stories list, not every Hacker News submission. | Hacker News API; JSON. | **Configured state:** enabled; poll every 30 minutes; no credentials. |

No Atom or additional regional instance is configured. Source selection supplies
trend observations; it does not authorize reuse of publisher creative or article
text. Setup materializes this registry, but does not prove live availability.
Source expansion belongs in [the roadmap](../plans/target-implementation.md).

### Source-instance registry

Every enabled external input has one persisted `DetectionSourceInstance` record
with a stable ID, source kind/version, publisher/provider display name,
endpoint/feed URL, declared delivery format, coverage note, enabled state,
expected poll cadence and availability interval, static trust weight,
`independence_group`, supported language/region scope, quota limit where
applicable, configuration fingerprint, and audit timestamps. An
`independence_group` represents one underlying publisher or platform: multiple
feeds from NASA share `nasa`; every regional YouTube chart shares `youtube`.
It never stores credentials. A run freezes the enabled source-instance
configuration it used so every observation remains interpretable.

Initial static trust weight is `1.00` for every initial source kind. This is not an
editorial-quality assertion: source-health reliability is calculated separately
from successful collection, timeliness, and completeness. A future change to a
source's static trust weight must be versioned and justified here.

## Canonicalization and clustering — `canonicalization_v2`

The active detector uses one deterministic canonicalization algorithm. It
preserves the provider title as evidence and creates a separate normalized key
for matching observations. Cross-source wording differences are evaluated by the separate semantic event
resolver after lexical clusters have been formed.

The detector creates a cluster from source observations without an
LLM. It preserves the original provider title/identity unchanged as evidence;
canonicalization creates only an additional deterministic matching key.

For a title-derived key, in this exact order:

1. Apply Unicode NFKC normalization and Unicode case folding.
2. Replace typographic apostrophe variants with `'`, dash variants with `-`,
   and `&` with the token `and`.
3. Replace every remaining punctuation or symbol run with one space; retain
   letters and numerals.
4. Collapse whitespace, trim it, and reject an empty result.

The algorithm does not remove stop words, stem words, translate,
transliterate, infer entities, or use fuzzy/semantic similarity. Numerals are
significant: `Artemis 2` and `Artemis 3` remain different keys. Source records
whose provider exposes a canonical identity use that identity as their
source-item key as well: Wikimedia uses its supplied canonical article title;
YouTube uses video ID; Hacker News uses item ID; publisher feeds use GUID, then
canonical link, then the normalized title. These item keys de-duplicate source
observations but do not by themselves determine cross-source clustering.

### Input, URL, and timestamp canonicalization

Current adapters reject oversized title/key/payload fields instead of truncating
them, reject invalid UTF-8 and encoded XML entity declarations, and preserve valid
normalized partial items plus safe rejection diagnostics. Malformed chart items
do not discard the other valid normalized records. Complete responses never score
NaN/boolean activity, duplicate provider identities or empty normalized titles.

Feed requests are unconditional in the current implementation: no conditional
cache headers are sent. An unexpected HTTP 304 without a validated cache body is
a typed failed attempt, not an empty successful feed. No conditional HTTP-cache
reuse is implemented. Error/redirect response streams are always closed, and
authorization/cookie headers are not forwarded to a different redirect host.

Collection is deterministic and never follows a feed item to obtain article
content. A configured feed endpoint may follow at most three HTTP redirects
with status `301`, `302`, `307`, or `308`; every hop and final URL is persisted.
Each hop and the final URL must be HTTPS and its host must be either the
configured endpoint host or an explicit `allowed_redirect_host` in the active
source-instance configuration. Any other status, scheme, host, loop, or fourth
hop is a rejected collection attempt. This policy applies to the configured
feed endpoint only, not item links.

When a feed item lacks a GUID, the collector uses a canonical URL key if
its link is an absolute HTTPS URL of at most 2,048 characters: lowercase scheme
and host; remove the default port and fragment; normalize dot path segments;
retain the path's percent encoding; remove `utm_*`, `gclid`, `fbclid`,
`mc_cid`, `mc_eid`, and `_ga` query parameters; then sort remaining
name/value pairs by their UTF-8 byte sequence. It never follows that link,
resolves short URLs, or discovers a provider canonical tag. An absent, invalid,
overlong, or non-HTTPS link falls back to the normalized title key. The fallback
is scoped to the source instance and collection day, preventing an undated
generic headline from collapsing unrelated history indefinitely.

All textual fields are decoded as UTF-8 after transport decoding and bounded
before parsing: at most 2 MiB compressed response bytes, 10 MiB decompressed
bytes, 512 Unicode scalar values for a title, 2,048 characters for a URL, and
16 KiB for retained item payload/summary. Oversized, invalid-encoding, or
structurally malformed input creates a typed rejection and makes the collection
incomplete; raw bodies are not retained. The persisted safe payload is a
bounded normalized metadata subset plus a SHA-256 of the received body.

A provider timestamp must parse as ISO-8601 with an explicit offset. A value
more than five minutes after `collected_at`, malformed, or absent is retained
only as a safe raw diagnostic; `effective_observed_at` becomes the first
`collected_at` and the observation receives `provider_time_fallback`. A valid
timestamp at most five minutes in the future is clamped to `collected_at` and
receives `provider_time_clamped`. Measurement-window assignment always uses
`effective_observed_at` and is consequently stable on retry.

Provider-native identities are durable even when display metadata changes. A
YouTube video ID or Hacker News item ID keeps one logical source item; each
collection stores a new immutable observation snapshot with its observed title
and metadata. A title change never produces a new source identity or changes an
already frozen cluster membership. The current title may be shown as a
non-authoritative latest display value.

Two records with the same canonical external item key from source instances in
the same `independence_group` remain separately retained for provenance. Within
one UTC window only the lexicographically smallest `(source_instance_id,
source_item_key)` is marked the activity contributor; the other receives a
`duplicate_suppressed` source-item event and cannot inflate feed activity or
breadth. Different independence groups remain independent evidence.

Rejected or excluded provider items never silently disappear. Each creates an
append-only `source_item_event` for its collection attempt with one exact
disposition: `rejected_invalid`, `rejected_oversized`, `excluded_dead`,
`excluded_deleted`, `excluded_non_story`, `excluded_out_of_scope`, or
`duplicate_suppressed`, plus source ordinal/key when available, safe reason,
and payload hash. A rejection/exclusion does not create a trend observation;
the sole exception is `duplicate_suppressed`, which accompanies its otherwise
valid retained observation but prevents it contributing to cluster activity.
In particular, the HN Top-100 attempt remains complete when a returned item is explicitly
dead, deleted, or non-story and has a corresponding excluded event; an absent
or unparsable required item response is incomplete.

## Semantic event resolution

The active Scout path is:

```text
observations → canonicalization_v2 → lexical clusters
  → local semantic event resolution → frozen resolved event clusters
  → attention_v3 scoring → shortlist_v2
```

`src/detection/semantic.py` owns the in-process resolver. It is not a separate
worker, generative model, external API, editorial judge, or pipeline router.
Its encoder is `sentence-transformers/all-MiniLM-L6-v2`, pinned to the exact
revision in the activated manifest. CPU inference uses two threads and batches
of 32 by default. Scout loads local safetensors only, disables remote code and
network model fetching, and embeds one representative title per lexical cluster,
never each repeated observation. Missing model files or invalid vectors fail the
run visibly; they do not silently turn inference off.

### Cluster and event gates

The active manifest owns all thresholds, windows, resource ceilings, entity
aliases/stopwords, event-action vocabulary, and negation terms. Defaults:

- recent evidence within 48 hours; pairwise evidence gap at most 24 hours;
- at most 256 recent lexical clusters, 16 peers per cluster, 2,048 pairs and
  eight lexical clusters per resolved group;
- cosine similarity rounded to six decimals; link at or above 0.82, separate
  at or below 0.55, unresolved between those thresholds;
- a shared extracted entity or exact stored canonical URL is required to
  consider a pair. Peers are ordered by time gap and lexical key, not activity.

Signals come only from stored titles, timestamps and canonical URLs. Capitalized
name tokens outside the configured stopword/action lists form conservative entity
sets; aliases normalize individual entity tokens. This is a heuristic, not a
full named-entity model. Entity tokens before/after the first event verb must
also agree. Reversed actor roles and passive-voice ambiguities remain unresolved
even at high similarity. Digits, decimals, magnitudes and percentages are retained;
missing numbers on one side leave the comparison unresolved. Incompatible
nonempty numeric sets, entity sets, action categories or negation signals veto
a link. A time gap over the configured bound is separate. Generic entity pages
without event-action context are unresolved, not automatically matched to news
about that entity. Inconsistent signals within one lexical cluster prevent its
semantic linking without altering lexical membership.

Similarity is computed only for pairs with equal nonempty entity and event-action
sets and compatible numeric/negation evidence. A high cosine value cannot
override a veto. Each evaluated pair records exactly `linked`, `unresolved`, or
`separate`, with the specific reason and observed signals. Uncompared, old,
capacity-excluded, and uncertain clusters remain separate singletons with an
unresolved explanation; capacity exclusion is not proof of a different event.

Grouping uses complete-link compatibility: every pair across two proposed groups
must independently qualify as linked. A–B and B–C do not imply A–C. Groups are
formed in deterministic similarity/key order; the resolved identity uses the
member with the smallest persisted trend ID, then lexical key. Its opportunity
identity is `trend:canonicalization_v2:<resolved_key>`. A selected constituent
already owned by another cluster/thread suppresses a second initial handoff.
Frozen membership, clusters, source observations and handoffs are not rewritten
when the resolver policy changes.

### Frozen evidence and replay

Scout first freezes its completed source attempts and health. It performs local
resolution outside a SQLite write transaction, then commits one immutable
`scout_event_resolutions` row under its running owner/claim-version fence. The
row binds the exact source snapshot hash to the resolver policy/model/revision,
lexical titles/keys and observation IDs, extracted signals, compared-pair
similarities/outcomes/reasons, and final partition. Every node has a reason,
including clusters excluded by bounds. Embedding hashes and counts are audit
information; scoring never requires the vectors to be regenerated.

Only a durable resolution can be scored. Once committed, retries and replay
read the same resolution without calling an encoder or consulting a new policy.
A crash before resolution commits may repeat inference on the same frozen
source input; it cannot publish any cluster from an uncommitted partition.
The SQL record and membership model are owned by [SQLite records](data/records.md).

### Conservative scoring credit

Semantic grouping collects evidence, not new corroboration credit. Each resolved
event inherits the entire score, source contributions, breadth, momentum,
persistence, prominence, reliability and eligibility of its strongest lexical
constituent. An eligible constituent sorts first, followed by score, breadth,
prominence and lexical key. Prominence populations are lexical populations, so
merging other events cannot boost an unrelated cluster's rank. The remaining
members are retained as inferred support with zero scoring contribution.

This means even a false semantic link cannot manufacture independent-source
breadth, cross-source growth, prominence or shortlist eligibility. It also means
a true semantic match across two otherwise uncorroborated sources cannot by
itself pass the bootstrap gate. This conservative recall tradeoff is explicit;
entity/title heuristics and MiniLM similarity are not proof of real-world identity.
The score breakdown names the scoring lexical key, resolved key, member keys and
resolution-run reference. It does not imply that inferred support was independently
verified.

## Scoring model — `attention_v3`

The score measures externally observable attention only. It does not decide
whether a topic is useful, safe, factual, or suitable for any pipeline; those
are Determination responsibilities.

Fast-source activity uses the trailing 24-hour UTC window; Wikimedia uses the
latest completed report day. Baselines use completed equivalent daily windows,
denoted `W`.
Fast provider collections remain individual immutable snapshots for audit,
health, and freshness; they do not multiply activity merely because the Scout
polled again. A cluster with no valid observation for a source kind in an
otherwise valid prior window has `A_s=0` for that baseline window. An
unavailable or degraded prior window is excluded rather than treated as zero.

For each cluster and source kind `s`:

- `A_s` is the source-specific current activity defined in the table below.
- `B_s` is the median `A_s` over the preceding 14 completed equivalent windows,
  excluding unavailable/degraded windows. History is **ready** only after at
  least seven valid windows.
- `G_s` is source-kind momentum:
  `clamp(log2((A_s + 1) / (B_s + 1)) / 2, 0, 1)`. A fourfold-or-greater lift
  therefore has momentum `1.0`.
- `P_s` is current-window prominence, normalized to `[0, 1]` from the source
  kind's ranked cluster population. For publisher feeds it ranks the number
  of distinct matching feeds; for Wikimedia it uses the provider article
  rank/view count.
- `R_s` is source reliability: static trust weight multiplied by source health
  (`1.0` healthy, `0.5` degraded, excluded when unavailable/failed).

When a source kind has insufficient history, its provisional `G_s` is
`0.5 × P_s` and is explicitly labeled **bootstrap**, never represented as
observed growth. This allows an early multi-source event to surface while
preventing a single un-baselined source from being selected by itself.

For each source kind and completed measurement window, its prominence
population is every distinct cluster with valid evidence for that
source kind in that window. Sort by `A_s` descending. Tied values receive their
midrank: a tie occupying ranks 2 and 3 has rank `2.5`. With population size
`N > 1`, `P_s = 1 - ((midrank - 1) / (N - 1))`; with `N = 1`, `P_s = 0.5`.
The frozen population, activity values, ranks, tie groups, and resulting `P_s`
are persisted in the score breakdown. Publisher-feed activity counts distinct
contributing `independence_group` values, never raw feed URLs; each platform
source's provider rank/score or view count remains its own source-local input.

### Source-specific activity and collection rules

The following table is part of `attention_v3`. Every source contribution
records its source instance, UTC measurement window, referenced collection
attempt IDs and observation IDs, completeness state, and the resulting
`A_s/B_s/G_s/P_s/R_s`. `B_s` is always the median of the preceding 14 valid
completed daily windows, and is history-ready after seven such windows. `G_s`
always uses the shared formula above; only `A_s` differs by source. The
prominence population is the valid current-window clusters from that
same source kind, never a cross-source population.

| Source kind | Window, raw observation, and exact `A_s` | Baseline, prominence, and repeat handling | Complete collection / stopping rule | Missing, degraded, and persistence treatment |
| --- | --- | --- | --- | --- |
| `publisher_feed_collector_v1` | `W` contains feed items with a provider `published_at` in `W`; if absent, use first `collected_at`. `A_s` is the number of distinct contributing `independence_group` values for the cluster, after per-item de-duplication. | `B_s` is the stated daily median. Rank clusters by `A_s` for `P_s`. The same GUID (or fallback item key) contributes once per `W`, even if returned by many polls; a different item from the same group does not increase `A_s`. | One HTTPS GET of each configured feed URL per scheduled attempt. A `200` response must parse with no fatal parser error and all returned entries must be processed; an unexpected `304` fails because requests are unconditional and no cache body is available. The collector does not follow linked article pages or feed pagination/`rel=next`. | A failed/invalid/incomplete feed attempt degrades that source instance. A valid earlier complete snapshot may support a degraded contribution only within the shared health window. Persistence counts `W` once when it has at least one valid matching item. |
| `wikimedia_enwiki_pageviews_v1` | `W` is the single completed UTC report day `D`; raw observation is the provider row's article title, rank, and pageviews for `D`. `A_s` is that reported pageview count (distinct article/day rows within the scoring lexical cluster; repeated polls do not add views). | `B_s` is the daily median for the same article/cluster. `P_s` ranks rows by `A_s`, with provider rank only as the deterministic tie-breaker. Re-fetching the same report date reuses its stored content-hash snapshot and contributes no second observation. | Request exactly the completed-day English Wikipedia Top Pageviews report. It is complete only when the response declares the requested report date and every returned content/article row has been parsed; do not fetch article bodies, redirects, or another date to fill gaps. The endpoint has no client pagination in this contract. | A missing, malformed, late, or partial report is degraded/unavailable under the shared health rule; its missing day is excluded from `B_s`. Persistence counts each valid report day once. |
| `youtube_most_popular_v1` | `W` contains all complete 30-minute chart snapshots. Raw observation is a video ID, rank `r` in `1..50`, and returned `viewCount`, `likeCount`, and `commentCount` when present. For a cluster, `A_s = max(51-r)` over its matching video observations in `W`; provider counters are retained as evidence but do not change `A_s`. | `B_s` is the daily median of this best-rank activity. `P_s` ranks clusters by `A_s`; the best rank, then video ID, breaks an equal-activity tie before the shared midrank calculation. The same video may appear in many snapshots but supplies only its best rank in `W`; separate videos in one cluster likewise use the best rank, not a sum. | Reserve one local quota unit before one request with exactly `part=snippet,statistics`, `chart=mostPopular`, `regionCode=US`, `maxResults=50`, no category, and no page token. Exactly 50 unique, ranked video records are required for completeness. `maxResults=50` is the intended chart limit, so no pagination is attempted. Every outbound request, including a retry that reaches YouTube, consumes one local reserved unit; no request starts after the 1,000-unit UTC-day ceiling. | A provider error, fewer than 50 valid ranked records, duplicate/missing ranks, or exhausted local ceiling makes the attempt incomplete; quota exhaustion is unavailable, not a zero-activity observation. A valid prior chart can contribute only while degraded under the shared health rule. Persistence counts `W` once if it has at least one valid matching chart observation. |
| `hacker_news_top_stories_v1` | `W` contains all complete 30-minute top-100 snapshots. Raw observation is HN item ID, rank `r` in `1..100`, and nonnegative score `q`. For a cluster, `A_s = max((101-r)/100 * log2(q+1))` over matching story observations in `W`, rounded to six decimals before ranking. | `B_s` is the daily median of that activity. `P_s` ranks clusters by `A_s`; best rank, then highest score, then lowest HN item ID breaks an equal-activity tie before shared midrank. A repeated item across polls contributes its single greatest calculated activity in `W`; multiple matching stories use the maximum, not a sum. | Fetch the Top Stories ID list once; preserve its full count/hash; select first 100 IDs in list order; request each selected item once in the same attempt. The intended chart limit is 100, so no further IDs/pages are fetched. Complete means list plus all 100 item responses arrived and every position is accounted for; deleted/dead/non-story items are recorded as excluded diagnostics rather than clusters. | Any missing list/item response, unaccounted rank, malformed score, or timeout makes the attempt incomplete. A valid prior snapshot can contribute only while degraded under the shared health rule. Persistence counts `W` once if it has at least one valid matching story observation. |

A source contribution is **healthy** when its latest complete valid collection
is no older than 1.5 times its configured availability interval and no later
collection has reported an error or incompleteness. It is **degraded** when a
valid complete collection exists within three availability intervals but the
latest attempt failed, was incomplete, or is late. It is **unavailable** when
no valid complete collection exists within three availability intervals, or
when the local YouTube quota ceiling is reached; unavailable contributions are
excluded until a later valid collection. `R_s` is static trust weight times
`1.0` for healthy or `0.5` for degraded. The precise health reason and
reference collection are persisted.

Cluster-level components are all in `[0, 1]`:

| Component | Definition | Weight |
| --- | --- | --- |
| Momentum | Reliability-weighted mean of contributing `G_s`. | 1/3 |
| Prominence | Reliability-weighted mean of contributing `P_s`. | 2/9 |
| Breadth | `min(1, contributing independence groups / 3)`. | 2/9 |
| Persistence | `min(1, distinct completed windows observed in the last 72 hours / 3)`. | 1/9 |
| Evidence recency | Persisted diagnostic value from the most recent source evidence; it is not included in the score. | 0.00 |
| Reliability | Reliability-weighted mean `R_s` for contributing sources. | 1/9 |

`attention_v3_score` is the weighted sum of the five weighted components, rounded to four
decimals. The persisted score breakdown includes each source-kind input,
history readiness/bootstrap state, every component, formula version, and final
score. No database query or dashboard calculation is allowed to alter it.

## Algorithm and evidence principles

- Normalize heterogeneous inputs before combining them. Publisher-feed item
  counts and Wikimedia page views are not directly comparable.
- Score momentum, prominence, corroboration breadth, persistence, evidence
  recency, and source reliability as distinct explainable factors. Evidence
  recency is diagnostic and a ranking tie-breaker; it is not part of the active
  normalized score. Persist score and canonicalization versions.
- Define first-observation behavior and deterministic tie-breakers:
  corroboration breadth, prominence, evidence recency, then stable cluster ID.
- Preserve source-instance identity, measurement windows, latency, fallback or
  degradation, and structured collection errors. A source’s stale/degraded
  state is visible and can be deterministically penalized or excluded.
- Retention is not selection: persist the complete scored set before applying
  any threshold or budget.
- Change an algorithm through versioned configuration and schema-aware
  records so immutable cluster evidence remains interpretable.

The detailed cluster/evidence fields, indexes, and uniqueness constraints
belong in [the data model](data-model.md). The dashboard presentation and
freshness rules belong in [the dashboard specification](dashboard.md).

## Shortlist policy — `shortlist_v2`

The shortlist is a separate deterministic policy, not an implication of a
cluster's score. It evaluates persisted clusters against the configured
eligibility rules, minimum score, and budget after the complete scored set is
durable.

An automatic cluster is eligible for its **initial selection** only when all
of these are true:

- `attention_v3_score >= 0.6000` for the normalized release;
- cluster reliability is at least `0.70`;
- it has either one history-ready contributing source kind or evidence from at
  least two independent contributing `independence_group` values;
- it has never completed an initial selection transaction for its opportunity
  identity and no other active cluster with the same opportunity identity
  already owns a seed thread; and
- it is within the global system-wide selection budget: at most two newly
  selected clusters in a rolling six hours and at most six in a rolling 24
  hours.

Eligible clusters are ordered by final score descending, then breadth,
prominence, evidence recency, and stable cluster ID. The shortlist selects
only as many clusters as remaining budget permits. Budget windows are half-open UTC
intervals `[now - 6h, now)` and `[now - 24h, now)` and count prior
`selected_at` timestamps, not cluster creation time. The shortlisted
cluster, current budget count, selection audit, trend thread, source-backed BriefRevision, and Determination
request are revalidated and committed in one SQLite write transaction; a
concurrent Scout cannot consume the same slot or cluster twice.

The shortlist assigns the deterministic route-neutral coverage identity while
creating the source-backed Revision 1. An unexpected coverage-identity collision
fails and rolls back the handoff transaction; it does not create a duplicate
brief or job. Existing selected event membership suppresses repeat initial
handoffs before this boundary.

The shortlist records the policy version, eligibility result/reason, rank,
selected time, and selected thread ID on the cluster audit trail. Clusters
that meet the gates but lose to the budget remain persisted as a durable
priority queue with `deferred_by_budget`. They are reconsidered whenever their
opportunity appears in a later evaluation; the queue does not silently expire
after 48 hours. The current source-evidence window still prevents old evidence
from being newly selected without a fresh observation.

- Initial selection is permanent for an event identity: later evaluations retain
  the selected thread and update only the cluster projection and new immutable
  topic snapshots. They do not create another automatic brief/request.
- Accepted, rejected or blocked Determination outcomes do not automatically
  re-enter the shortlist. There is no automatic recurrence or blocked-route
  recheck worker.
- A human may refine the existing thread, producing a new immutable brief and
  Determination request while retaining original Detection evidence.
- Recovery resumes the same persisted selection; it does not create replacement
  threads from unchanged evidence.

Evidence, opportunity, coverage, domain-angle, canonical-content, output, and
publication identities solve different duplication problems. A single hash must not be
reused as a shortcut for all of them.

## Change and acceptance requirements

Before changing a detection algorithm or source, document the score/version,
input units, normalization, selection impact, and immutable evidence requirements
in this specification. Add boundary tests for:

- source registry/allowlist, normalization, source degradation, and retained
  provenance;
- canonicalization, clustering, score breakdown, bootstrap behavior, and
  deterministic ties;
- persistence of every scored cluster before selection;
- shortlist threshold/budget behavior and source-backed thread creation; and
- selected-event ownership across changing windows and idempotent recovery.

Detection quality is observed through the dashboard's detection view; it must
show source-instance configuration/health, evidence, source-kind score inputs,
formula/policy versions, selection outcome, and the resulting trend thread and
revision where one exists.
