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
Candidates that do not currently meet every eligibility gate use
`eligibility_status=observed` with a specific reason; `eligible` is reserved
for a candidate that can enter the shortlist budget transaction now.

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
   seed `ContentThread` with `origin=trend` plus its pending `IntakeRequest`.
   The records retain the candidate ID, producing detection run, evidence
   fingerprint, and exact evidence snapshot. The seed thread has no editorial
   coverage identity yet.
6. Idea Intake claims that request and freezes a source-backed Revision 1. It
   assigns editorial coverage under `coverage_normalization_v2`, or performs
   the documented collision merge. Its `source_snapshot_json` carries the
   selected candidate evidence and producing detection run; Determination never
   performs a later topic-string lookup.

No source, detector, or shortlist process calls Idea Intake or Determination
directly.

### Collection and evaluation boundary — `scout_evaluation_v1`

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
It computes all candidates only from that frozen set. Completion atomically persists every score snapshot
and candidate, then performs any shortlist selection. A collection that
finishes later belongs to a later evaluation slot; it cannot silently alter
this evaluation's candidates or selection.

## Initial target source portfolio

Detection sources are system-wide attention signals. They are not owned by O2
or any other content pipeline; Determination decides which enabled domain pipelines, if
any, can use a selected opportunity.

Source instances and aliases are immutable records materialized from the active
non-secret configuration release. The Scout reads only that release; it never
adds, edits, enables, or disables a feed/API source itself. Each collection and
evaluation freezes the release fingerprint that supplied its source/scoring
policy. See the [Configuration control plane](configuration.md).

The target-enabled source kinds are:

| Source kind / stable ID | Scope and measurement | Collection policy | Required provenance and guardrails |
| --- | --- | --- | --- |
| `publisher_feed_collector_v1` | An operator-approved publisher feed. One source instance is one exact feed URL, which declares either RSS or Atom as its delivery format; the collector does not combine both formats for one source. The raw measure is unique published feed items that join a canonical candidate cluster during a trailing 24-hour UTC window. | Poll each enabled feed every 15 minutes. De-duplicate by feed GUID, or normalized link/title when GUID is absent. | Store source-instance ID, publisher/display name, feed URL, declared delivery format, item GUID/link, published/collected time, title, and raw item count. Only allow HTTPS feeds with an explicit coverage note. A feed is enabled only through the persisted source registry. |
| `wikimedia_enwiki_pageviews_v1` | The daily most-viewed English Wikipedia articles (`en.wikipedia.org`, all access, all agents) for the preceding completed UTC day. The raw measure is the reported daily view count and rank. | Fetch once after the provider's daily data is available; subsequent Scout polls reuse the same completed-day snapshot. | Store article identifier/title, report date, rank, view count, endpoint/version, and collection time. Exclude non-content/navigation entries and duplicate article identities before clustering. |
| `youtube_most_popular_v1` | The configured first 50 positions of the returned `mostPopular` video chart for one region across all categories. The initial instance is the US chart. The raw measure is chart rank plus returned video statistics at collection time; it is not search or keyword-trend data. | Poll every 30 minutes using exactly one `videos.list` request with `chart=mostPopular`, `regionCode=US`, `maxResults=50`, and `part=snippet,statistics`; omit `videoCategoryId` and `pageToken`. Enforce a local ceiling of 1,000 quota units per UTC day. Stop collection and record `quota_limited` once the ceiling is reached. | Store video ID, title, channel ID/title, published time, category, chart position, returned statistics, collection time, request parameters, and provider/API version. Never use `search.list`. |
| `hacker_news_top_stories_v1` | The configured first 100 positions of the published Hacker News Top Stories ID list and each listed story's current rank and score. The raw measure is story rank plus score at collection time. | Poll the Top Stories list every 30 minutes, retain its full-list hash/count, take positions 1–100, then fetch one detail record for every selected ID in that same attempt. | Store HN item ID, title, outbound URL when present, score, rank, author, provider time, collection time, and item type. Ignore deleted/dead/non-story entries for candidate creation but retain the collection diagnostic. |

The Wikimedia Analytics API provides the project pageview/top-pages data used by
the second source. This provider fact was verified on 2026-08-29; endpoint,
availability, and attribution requirements must be rechecked before a provider
change. See the official [Wikimedia Analytics API project-metrics reference](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/examples/project-metrics.html).

The YouTube adapter uses the official [`videos.list` chart endpoint](https://developers.google.com/youtube/v3/docs/videos/list),
which documents `mostPopular`, `regionCode`, and its one-unit quota cost. The
local ceiling is a Content Factory safety limit, not a claim about a provider's
default quota; recheck the [YouTube quota documentation](https://developers.google.com/youtube/v3/getting-started)
before changing it. The Hacker News adapter uses the public
[Hacker News API](https://github.com/HackerNews/API) Top Stories list and item
records. These provider facts were verified on 2026-09-03.

`publisher_feed_collector_v1` is an allowlisted collector, not a hidden
hard-coded publisher list. RSS and Atom are standard delivery formats, not
sources: each configured publisher feed chooses the one format returned by its
official URL. Individual feeds are source-instance configuration and may be
enabled or disabled without changing a detection algorithm. No other source
kind is enabled until this specification is updated and its source instance is
added to the registry.

### Initial target source instances

The first configured publisher-feed source is deliberately narrow in scope: it
validates official feed ingestion and its complete evidence trail before the
system adopts a broader publisher portfolio.

| Source-instance ID | Provider and coverage | Interface | Policy |
| --- | --- | --- | --- |
| `nasa_recently_published_rss_v1` | NASA — all recently published web content across `nasa.gov`. This is NASA's own current-content stream; it is not a measure of all science, space, or general-news attention. | [`https://www.nasa.gov/feed/`](https://www.nasa.gov/feed/) — RSS 2.0. The endpoint was directly checked on 2026-09-05 and returned `application/rss+xml`. NASA describes it as its feed for all recent web content. | **Target enabled state:** enabled; poll every 15 minutes; no credentials. Retain only the feed-supplied provenance and metadata needed for detection. Do not fetch or scrape linked article bodies. |
| `wikimedia_enwiki_daily_v1` | English Wikipedia — completed daily Top Pageviews report. | Wikimedia Analytics API/data response. | **Target enabled state:** enabled; fetch once for each completed UTC day after availability. |
| `youtube_us_most_popular_v1` | YouTube — US `mostPopular` chart across all categories. It is the complete chart returned by the provider, not all videos published in the US. | YouTube Data API `videos.list`; JSON. | **Target enabled state:** enabled; poll every 30 minutes; 1,000 local quota-unit ceiling per UTC day. The data model permits further regional instances, but Korea is not enabled in the initial roster. |
| `hacker_news_top_stories_v1` | Hacker News — Top Stories ranking. It is the complete provider Top Stories list, not every Hacker News submission. | Hacker News API; JSON. | **Target enabled state:** enabled; poll every 30 minutes; no credentials. |

No Atom source is target-configured initially. Korea is a planned possible
second YouTube region but remains disabled until the US evidence/scoring path
has been observed in operation. A future publisher or source instance may be
added only after its exact official interface, coverage declaration, and
permitted use have been reviewed and recorded. Source selection does not
authorize reuse of publisher creative or article text in a generated post; it
supplies trend observations only. This target configuration does not claim that
the stale implementation has already created the SQLite registry rows or
started collecting these sources.

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
configuration it used so historical observations remain interpretable.

Initial static trust weight is `1.00` for every initial source kind. This is not an
editorial-quality assertion: source-health reliability is calculated separately
from successful collection, timeliness, and completeness. A future change to a
source's static trust weight must be versioned and justified here.

## Canonicalization and clustering — `canonicalization_v1`

The detector creates a candidate cluster from source observations without an
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

### Input, URL, and timestamp canonicalization — `collection_input_v1`

Collection is deterministic and never follows a feed item to obtain article
content. A configured feed endpoint may follow at most three HTTP redirects
with status `301`, `302`, `307`, or `308`; every hop and final URL is persisted.
Each hop and the final URL must be HTTPS and its host must be either the
configured endpoint host or an explicit `allowed_redirect_host` in the active
source-instance configuration. Any other status, scheme, host, loop, or fourth
hop is a rejected collection attempt. This policy applies to the configured
feed endpoint only, not item links.

When a feed item lacks a GUID, the collector uses a `canonical_link_v1` key if
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
valid retained observation but prevents it contributing to candidate activity.
In particular, the HN Top-100 attempt remains complete when a returned item is explicitly
dead, deleted, or non-story and has a corresponding excluded event; an absent
or unparsable required item response is incomplete.

Observations with the same `canonicalization_v1` title key join one cluster.
Non-identical keys join only through an active, versioned
`DetectionClusterAlias` mapping from an exact normalized alias key to a target
cluster key. Alias mappings are explicit configuration with a recorded reason
and audit history; the detector never proposes or creates an alias. When a
provider supplies a canonical identity, use it; otherwise do not crawl or
follow article redirects. Different language variants remain different clusters
unless an explicit alias maps them. The candidate's immutable **opportunity
identity** is `trend:<canonicalization_version>:<cluster_key>`. It identifies
the observed attention cluster only; it is never called editorial coverage and
is not a pipeline choice. A selected candidate creates a seed thread with that
opportunity retained through its candidate FK. Idea Intake later assigns the
distinct editorial coverage identity from the frozen brief.

Cluster membership is append-only evidence. Changing an alias configuration
affects future scoring under its new version and never rewrites previously
frozen candidate evidence, selection, revision, or decision records.

## Scoring model — `attention_v1`

The score measures externally observable attention only. It does not decide
whether a topic is useful, safe, factual, or suitable for any pipeline; those
are Determination responsibilities.

All scoring calculations use completed 24-hour UTC windows, denoted `W`.
Fast provider collections remain individual immutable snapshots for audit,
health, and freshness; they do not multiply activity merely because the Scout
polled again. A candidate with no valid observation for a source kind in an
otherwise valid prior window has `A_s=0` for that baseline window. An
unavailable or degraded prior window is excluded rather than treated as zero.

For each candidate and source kind `s`:

- `A_s` is the source-specific current activity defined in the table below.
- `B_s` is the median `A_s` over the preceding 14 completed equivalent windows,
  excluding unavailable/degraded windows. History is **ready** only after at
  least seven valid windows.
- `G_s` is source-kind momentum:
  `clamp(log2((A_s + 1) / (B_s + 1)) / 2, 0, 1)`. A fourfold-or-greater lift
  therefore has momentum `1.0`.
- `P_s` is current-window prominence, normalized to `[0, 1]` from the source
  kind's ranked candidate population. For publisher feeds it ranks the number
  of distinct matching feeds; for Wikimedia it uses the provider article
  rank/view count.
- `R_s` is source reliability: static trust weight multiplied by source health
  (`1.0` healthy, `0.5` degraded, excluded when unavailable/failed).

When a source kind has insufficient history, its provisional `G_s` is
`0.5 × P_s` and is explicitly labeled **bootstrap**, never represented as
observed growth. This allows an early multi-source event to surface while
preventing a single un-baselined source from being selected by itself.

For each source kind and completed measurement window, its prominence
population is every distinct candidate cluster with valid evidence for that
source kind in that window. Sort by `A_s` descending. Tied values receive their
midrank: a tie occupying ranks 2 and 3 has rank `2.5`. With population size
`N > 1`, `P_s = 1 - ((midrank - 1) / (N - 1))`; with `N = 1`, `P_s = 0.5`.
The frozen population, activity values, ranks, tie groups, and resulting `P_s`
are persisted in the score breakdown. Publisher-feed activity counts distinct
contributing `independence_group` values, never raw feed URLs; each platform
source's provider rank/score or view count remains its own source-local input.

### Source-specific activity and collection rules

The following table is part of `attention_v1`. Every source contribution
records its source instance, UTC measurement window, referenced collection
attempt IDs and observation IDs, completeness state, and the resulting
`A_s/B_s/G_s/P_s/R_s`. `B_s` is always the median of the preceding 14 valid
completed daily windows, and is history-ready after seven such windows. `G_s`
always uses the shared formula above; only `A_s` differs by source. The
prominence population is the valid current-window candidate clusters from that
same source kind, never a cross-source population.

| Source kind | Window, raw observation, and exact `A_s` | Baseline, prominence, and repeat handling | Complete collection / stopping rule | Missing, degraded, and persistence treatment |
| --- | --- | --- | --- | --- |
| `publisher_feed_collector_v1` | `W` contains feed items with a provider `published_at` in `W`; if absent, use first `collected_at`. `A_s` is the number of distinct contributing `independence_group` values for the candidate, after per-item de-duplication. | `B_s` is the stated daily median. Rank clusters by `A_s` for `P_s`. The same GUID (or fallback item key) contributes once per `W`, even if returned by many polls; a different item from the same group does not increase `A_s`. | One HTTPS GET of each configured feed URL per scheduled attempt. A `200` response must parse with no fatal parser error and all returned entries must be processed; a `304` reuses the last complete snapshot and is not a new observation. The collector does not follow linked article pages or feed pagination/`rel=next`. | A failed/invalid/incomplete feed attempt degrades that source instance. A valid earlier complete snapshot may support a degraded contribution only within the shared health window. Persistence counts `W` once when it has at least one valid matching item. |
| `wikimedia_enwiki_pageviews_v1` | `W` is the single completed UTC report day `D`; raw observation is the provider row's article title, rank, and pageviews for `D`. `A_s` is that reported pageview count (one canonical article per cluster; if an explicit alias joins several rows, use their sum). | `B_s` is the daily median for the same article/cluster. `P_s` ranks rows by `A_s`, with provider rank only as the deterministic tie-breaker. Re-fetching the same report date reuses its stored content-hash snapshot and contributes no second observation. | Request exactly the completed-day English Wikipedia Top Pageviews report. It is complete only when the response declares the requested report date and every returned content/article row has been parsed; do not fetch article bodies, redirects, or another date to fill gaps. The endpoint has no client pagination in this contract. | A missing, malformed, late, or partial report is degraded/unavailable under the shared health rule; its missing day is excluded from `B_s`. Persistence counts each valid report day once. |
| `youtube_most_popular_v1` | `W` contains all complete 30-minute chart snapshots. Raw observation is a video ID, rank `r` in `1..50`, and returned `viewCount`, `likeCount`, and `commentCount` when present. For a candidate, `A_s = max(51-r)` over its matching video observations in `W`; provider counters are retained as evidence but do not change `A_s`. | `B_s` is the daily median of this best-rank activity. `P_s` ranks clusters by `A_s`; the best rank, then video ID, breaks an equal-activity tie before the shared midrank calculation. The same video may appear in many snapshots but supplies only its best rank in `W`; separate videos in one cluster likewise use the best rank, not a sum. | Reserve one local quota unit before one request with exactly `part=snippet,statistics`, `chart=mostPopular`, `regionCode=US`, `maxResults=50`, no category, and no page token. Exactly 50 unique, ranked video records are required for completeness. `maxResults=50` is the intended chart limit, so no pagination is attempted. Every outbound request, including a retry that reaches YouTube, consumes one local reserved unit; no request starts after the 1,000-unit UTC-day ceiling. | A provider error, fewer than 50 valid ranked records, duplicate/missing ranks, or exhausted local ceiling makes the attempt incomplete; quota exhaustion is unavailable, not a zero-activity observation. A valid prior chart can contribute only while degraded under the shared health rule. Persistence counts `W` once if it has at least one valid matching chart observation. |
| `hacker_news_top_stories_v1` | `W` contains all complete 30-minute top-100 snapshots. Raw observation is HN item ID, rank `r` in `1..100`, and nonnegative score `q`. For a candidate, `A_s = max((101-r)/100 * log2(q+1))` over matching story observations in `W`, rounded to six decimals before ranking. | `B_s` is the daily median of that activity. `P_s` ranks clusters by `A_s`; best rank, then highest score, then lowest HN item ID breaks an equal-activity tie before shared midrank. A repeated item across polls contributes its single greatest calculated activity in `W`; multiple matching stories use the maximum, not a sum. | Fetch the Top Stories ID list once; preserve its full count/hash; select first 100 IDs in list order; request each selected item once in the same attempt. The intended chart limit is 100, so no further IDs/pages are fetched. Complete means list plus all 100 item responses arrived and every position is accounted for; deleted/dead/non-story items are recorded as excluded diagnostics rather than candidates. | Any missing list/item response, unaccounted rank, malformed score, or timeout makes the attempt incomplete. A valid prior snapshot can contribute only while degraded under the shared health rule. Persistence counts `W` once if it has at least one valid matching story observation. |

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

Candidate-level components are all in `[0, 1]`:

| Component | Definition | Weight |
| --- | --- | --- |
| Momentum | Reliability-weighted mean of contributing `G_s`. | 0.30 |
| Prominence | Reliability-weighted mean of contributing `P_s`. | 0.20 |
| Breadth | `min(1, contributing independence groups / 3)`. | 0.20 |
| Persistence | `min(1, distinct completed windows observed in the last 72 hours / 3)`. | 0.10 |
| Freshness | `clamp(1 - age_hours / 48, 0, 1)` using the most recent source evidence. | 0.10 |
| Reliability | Reliability-weighted mean `R_s` for contributing sources. | 0.10 |

`attention_v1_score` is the weighted sum of those components, rounded to four
decimals. The persisted score breakdown includes each source-kind input,
history readiness/bootstrap state, every component, formula version, and final
score. No database query or dashboard calculation is allowed to alter it.

### Implementation status

The current detection path is `src/detection/`: its Scout implements and
persists `attention_v1` source components, history/bootstrap state, prominence
ranking, deterministic ordering, and shortlist gates. Its boundary coverage is
in `tests/test_detection_dashboard_slice.py`.

The older `src/intelligence/` modules remain compatibility code for legacy
fixtures and must not be used as evidence of the active detection contract or
as a new worker entrypoint. Any future change to `attention_v1` still requires
the boundary tests listed below.

## Algorithm and evidence principles

- Normalize heterogeneous inputs before combining them. Publisher-feed item
  counts and Wikimedia page views are not directly comparable.
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
  least two independent contributing `independence_group` values;
- it has never completed an initial selection transaction for its opportunity
  identity and no other active candidate with the same opportunity identity
  already owns a seed thread; and
- it is within the global system-wide selection budget: at most two newly
  selected candidates in a rolling six hours and at most six in a rolling 24
  hours.

Eligible candidates are ordered by final score descending, then breadth,
prominence, freshness, and stable candidate ID. The shortlist selects only as
many candidates as remaining budget permits. Budget windows are half-open UTC
intervals `[now - 6h, now)` and `[now - 24h, now)` and count prior
`selected_at` timestamps, not candidate creation time. The shortlisted
candidate, current budget count, selection audit, trend thread, and Intake
request are revalidated and committed in one SQLite write transaction; a
concurrent Scout cannot consume the same slot or candidate twice.

The shortlist cannot test editorial coverage identity because that identity
does not exist until Idea Intake freezes Revision 1. Duplicate editorial
coverage is resolved later by the `coverage_normalization_v2` collision
transaction: it preserves this candidate as evidence, closes an unused seed
thread, and creates no duplicate revision or content job.

The shortlist records the policy version, eligibility result/reason, rank,
selected time, and selected thread ID on the candidate audit trail. Candidates
that meet the score threshold but lose to the budget remain persisted and
visible as `deferred_by_budget`; they are re-evaluated only while their newest
evidence is less than 48 hours old. At 48 hours, the audit records
`deferred_stale`; the stale evidence cannot later receive an automatic initial
selection.

- A candidate with an `accepted` Determination decision is consumed for
  automatic routing permanently, including an accepted multi-domain or reuse
  outcome; time passing alone does not reconsider it. Skipped/blocked siblings
  do not become fresh candidates after cooldown. Blocked-route rechecks are
  explicit Intake/Determination commands on the existing thread.
- A candidate with a `not_recommended` determination outcome may re-enter only
  after three days from that decision, with new source evidence no older than
  48 hours, and under `recurrence_materiality_v1` only when either (a) at least
  one contributing independence group was absent from the frozen evidence of
  the prior determination, or (b) its final attention score increased by at
  least `0.1500` from that frozen score. A fingerprint change alone is not
  material. The shortlist appends a `ThreadEvidenceEvent` and pending
  `IntakeRequest` to its existing trend thread. Idea Intake may then create an
  `evidence_refresh` Brief Revision; no duplicate thread is created.
- Worker recovery resumes the same persisted selection/thread; it does not
  create a replacement from unchanged evidence.
- A human may continue an existing content thread and make an intentional new
  revision. That is auditable rework, not automatic trend duplication.
- Future recurring coverage needs a separately documented editorial
  freshness/version policy; it must not weaken the rules above implicitly.

Evidence, opportunity, coverage, domain-angle, canonical-content, output, and
publication identities solve different duplication problems. A single hash must not be
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
