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

## Initial target source portfolio

Detection sources are system-wide attention signals. They are not owned by O2
or any other content pipeline; Determination decides which enabled pipeline, if
any, can use a selected opportunity.

The target-enabled source kinds are:

| Source kind / stable ID | Scope and measurement | Collection policy | Required provenance and guardrails |
| --- | --- | --- | --- |
| `publisher_feed_collector_v1` | An operator-approved publisher feed. One source instance is one exact feed URL, which declares either RSS or Atom as its delivery format; the collector does not combine both formats for one source. The raw measure is unique published feed items that join a canonical candidate cluster during a trailing 24-hour UTC window. | Poll each enabled feed every 15 minutes. De-duplicate by feed GUID, or normalized link/title when GUID is absent. | Store source-instance ID, publisher/display name, feed URL, declared delivery format, item GUID/link, published/collected time, title, and raw item count. Only allow HTTPS feeds with an explicit coverage note. A feed is enabled only through the persisted source registry. |
| `wikimedia_enwiki_pageviews_v1` | The daily most-viewed English Wikipedia articles (`en.wikipedia.org`, all access, all agents) for the preceding completed UTC day. The raw measure is the reported daily view count and rank. | Fetch once after the provider's daily data is available; subsequent Scout polls reuse the same completed-day snapshot. | Store article identifier/title, report date, rank, view count, endpoint/version, and collection time. Exclude non-content/navigation entries and duplicate article identities before clustering. |
| `youtube_most_popular_v1` | The complete returned `mostPopular` video chart for one configured region and all categories. The initial instance is the US chart. The raw measure is chart rank plus the returned video statistics at collection time; it is not search or keyword-trend data. | Poll every 30 minutes using only `videos.list` with `chart=mostPopular` and `regionCode=US`; omit `videoCategoryId`. Enforce a local ceiling of 1,000 quota units per UTC day. Stop collection and record `quota_limited` once the ceiling is reached. | Store video ID, title, channel ID/title, published time, category where returned, chart position, returned statistics, collection time, request parameters, and provider/API version. Never use `search.list`. |
| `hacker_news_top_stories_v1` | The complete published Hacker News Top Stories ID list and each listed story's current rank and score. The raw measure is story rank plus score at collection time. | Poll the Top Stories list every 30 minutes; fetch story detail only for an unseen ID or a listed story whose stored score/metadata changed. | Store HN item ID, title, outbound URL when present, score, rank, author, provider time, collection time, and item type. Ignore deleted/dead/non-story entries for candidate creation but retain the collection diagnostic. |

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

Observations with the same `canonicalization_v1` title key join one cluster.
Non-identical keys join only through an active, versioned
`DetectionClusterAlias` mapping from an exact normalized alias key to a target
cluster key. Alias mappings are explicit configuration with a recorded reason
and audit history; the detector never proposes or creates an alias. When a
provider supplies a canonical identity, use it; otherwise do not crawl or
follow article redirects. Different language variants remain different clusters
unless an explicit alias maps them. The candidate's route-neutral coverage
identity is `trend:<canonicalization_version>:<cluster_key>` and is created
with the selected trend thread; it is not a pipeline choice.

Cluster membership is append-only evidence. Changing an alias configuration
affects future scoring under its new version and never rewrites previously
frozen candidate evidence, selection, revision, or decision records.

## Scoring model — `attention_v1`

The score measures externally observable attention only. It does not decide
whether a topic is useful, safe, factual, or suitable for any pipeline; those
are Determination responsibilities.

All calculations use completed 24-hour UTC windows. The Scout may run every 15
minutes, but it never treats repeated collection of the same unchanged
Wikimedia daily report as new attention. RSS activity is aggregated over the
trailing 24-hour window after feed-item de-duplication.

For each candidate and source kind `s`:

- `A_s` is current normalized activity: distinct matching publisher-feed
  instances, or reported page views for Wikimedia.
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
- it has no existing thread with the same coverage identity; and
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

The shortlist records the policy version, eligibility result/reason, rank,
selected time, and selected thread ID on the candidate audit trail. Candidates
that meet the score threshold but lose to the budget remain persisted and
visible as `deferred_by_budget`; they are re-evaluated only while their newest
evidence is less than 48 hours old. At 48 hours, the audit records
`deferred_stale`; the stale evidence cannot later receive an automatic initial
selection.

- A candidate with an `accepted` Determination decision is consumed for
  automatic routing permanently; time passing alone does not reconsider it.
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
