# Detection

**Owner:** Source behavior, lexical/semantic resolution, deterministic attention
scoring, selection and frozen evidence. Commands belong to
[operations](../current-state.md); settings and exact source endpoints belong to
the [release manifest](../../config/releases/detection.json).

## Architecture

```text
Configured Source / Feed → adapter → CollectionResult → Collector → SQLite
→ Scout frozen input → lexical clusters → frozen local semantic resolution
→ immutable scores + Cluster projection → selected Opportunity handoff
```

`adapters.py` handles bounded external reads; `collector.py` owns attempts and
observations. `semantic.py` resolves events locally, `hybrid.py` evaluates frozen
attention evidence, and `scout.py` commits scores and selection. Detection is
LLM-free and domain-neutral. It never invokes Intake or Determination. An
Opportunity exists only after the same transaction commits its trend thread,
source-backed brief and DeterminationRequest. Human ideas enter through the
separate [Intake boundary](idea-intake-and-determination.md).

Source activity, provider rank/votes, semantic cosine similarity, Detection
attention score and editorial fit are different measurements. The dashboard
shows Raw Feed Items (`trend_observations`), Clusters (`trend_candidates`),
committed Opportunities and downstream ContentJobs. An observation is one
measurement, not necessarily a unique provider item.

Storage monitoring is advisory throughout Detection; actual write errors still fail.

## Status ownership

| Layer | Current behavior |
| --- | --- |
| Collection | A scheduled source attempt is claimed, runs and completes, retries or fails with typed evidence. |
| Source health | Healthy, degraded, unavailable, failed or quota-limited evidence; never a Selection state. |
| Raw Feed Item | Immutable observation with provenance and per-evaluation scoring credit; no Selection state. |
| Cluster `observed` | One or more evidence/identity gates fail, with an explicit reason. |
| Cluster `eligible` | Evidence gates pass; selection has not committed its handoff. |
| Cluster `deferred_by_budget` | Eligible but global selection capacity is exhausted. |
| Cluster `selected` | Selection and the initial trend handoff committed atomically. |

The SQL enum also retains `deferred_stale`, `rejected_cooldown`, `consumed` and
`reconsiderable`; no current worker writes these projection states. They are not
active dashboard filters. Determination does not consume or reset `selected`;
its own request/decision records describe downstream progress.

## Configured sources

All nine sources are enabled and keyless. Domains are editorial remits, not
source ownership: any selected source evidence can reach any suitable domain.
The manifest owns endpoints, cadences, quotas, trust weights, independence
groups, allowlists and resolver thresholds. Configuration activation freezes
source identities and fingerprints; workers do not edit the registry.

| Source-instance ID | Provider / coverage | Endpoint |
| --- | --- | --- |
| `wikimedia_enwiki_daily_v1` | Wikimedia — English Wikipedia completed daily Top Pageviews report. | [Official endpoint](https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia.org/all-access) |
| `hacker_news_top_stories_v1` | Hacker News — First 100 positions of the Hacker News Top Stories list. | [Official endpoint](https://hacker-news.firebaseio.com/v0) |
| `openai_news_rss_v1` | OpenAI — Official AI releases and research updates. | [Official endpoint](https://openai.com/news/rss.xml) |
| `google_ai_rss_v1` | Google AI — Official Google AI updates. | [Official endpoint](https://blog.google/innovation-and-ai/technology/ai/rss/) |
| `nature_psychology_rss_v1` | Nature Psychology — Psychology research and news; linked evidence, not full articles. | [Official endpoint](https://www.nature.com/subjects/psychology.rss) |
| `sciencedaily_psychology_rss_v1` | ScienceDaily Psychology — Psychology research summaries; claims require their underlying evidence. | [Official endpoint](https://www.sciencedaily.com/rss/mind_brain/psychology.xml) |
| `voa_grammar_rss_v1` | VOA Everyday Grammar — English grammar and usage lessons. | [Official endpoint](https://learningenglish.voanews.com/api/zoroqql-vomx-tpeptpqq) |
| `voa_expressions_rss_v1` | VOA Words and Their Stories — English idioms and expressions. | [Official endpoint](https://learningenglish.voanews.com/api/zmypyl-vomx-tpeyry_) |
| `cambridge_words_rss_v1` | Cambridge About Words — English vocabulary, expressions and usage. | [Official endpoint](https://dictionaryblog.cambridge.org/feed/) |


The two VOA feeds share one independence group. Multiple feeds from one publisher
cannot manufacture independent corroboration. Collection retains titles, links,
times and minimal metadata; it never fetches linked article bodies.

### Adapter behavior

- **Publisher RSS/Atom:** One unconditional request per attempt, using the
  configured format. Items are sorted by supplied publication time, with undated
  items last, then bounded to 100. Older excess entries are recorded as outside
  the window, not a failed response. Malformed selected entries make collection
  incomplete. GUID is the preferred item key; normalized link or day-scoped title
  supplies the fallback. No article fetching, feed pagination or cached 304 body.
- **Wikimedia:** One completed UTC report date is frozen before fetching. The
  response must declare that date; retries cannot silently switch days. Valid
  content rows retain article, rank and views; navigation/duplicate rows are
  excluded. A repeated identical daily report does not add observations. Report
  end time determines evidence age.
- **Hacker News:** Fetch the Top Stories list and account for each selected
  position (up to 100) with one detail response. Preserve full-list hash/count.
  Dead/deleted/non-story responses create exclusion evidence; missing or malformed
  detail responses make the attempt incomplete. Activity measures collection-time
  rank and score, not story publication time.

Source failures retain safe request/execution/item evidence without turning a
partial response into scoring observations. Quota reservations count outbound
requests across compatible release activation. A retry reuses its frozen
source/request identity and creates another request-execution record.

## Canonicalization and clustering — `canonicalization_v2`

The active detector uses one deterministic canonicalization algorithm. It
preserves the provider title as evidence and creates a separate normalized key
for matching observations. Cross-source wording differences are evaluated by the separate semantic event
resolver after lexical clusters have been formed.

For a title-derived key, in this exact order:

1. Apply Unicode NFKC normalization and Unicode case folding.
2. Replace typographic apostrophe variants with `'`, dash variants with `-`,
   and `&` with the token `and`.
3. Replace every remaining punctuation or symbol run with one space; retain
   letters and numerals.
4. Collapse whitespace, trim it, and reject an empty result.

The algorithm does not remove stop words, stem words, translate,
transliterate, infer entities, or use fuzzy/semantic similarity. Numerals are
significant: `Model 2` and `Model 3` remain different keys. Source records
whose provider exposes a canonical identity use that identity as their
source-item key as well: Wikimedia uses its supplied canonical article title;
Hacker News uses item ID; publisher feeds use GUID, then
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

Adapters require an explicit timezone in external RSS/Atom timestamps, convert
them to UTC-naive seconds, and pass that normalized value to collection. Missing
or malformed external times become absent. Collection accepts the normalized
UTC value: valid publication time determines the feed's measurement window.
A time more than five minutes after collection falls back to the item's first
collection time; one within five minutes is clamped to collection time. Status
metadata distinguishes valid, clamped and fallback evidence. Retry/repeated polls
cannot move an undated item's first-seen window. HN uses collection time for its
rank/score measurement regardless of publication time.

Provider-native identities are durable even when display metadata changes. A
Hacker News item ID keeps one logical source item; each
collection stores a new immutable observation snapshot with its observed title
and metadata. A title change never produces a new source identity or changes an
already frozen cluster membership. The current title may be shown as a
non-authoritative latest display value.

Matching items from source instances in the same independence group remain
separate provenance records. Collection flags known duplicate contributors;
it never rewrites completed observations when another source arrives. Scout
resolves the smallest `(source_instance_id, source_item_key)` contributor from
its frozen attempt set. Other members retain evidence with no extra activity or
breadth credit. Different independence groups remain independent evidence.

Rejected or excluded items create append-only source-item events with safe
reason, ordinal/key and payload hash. They do not create observations except
valid duplicate-suppressed evidence, which remains visible with zero activity
credit. Required HN positions still need an accounted response.

## Semantic event resolution

Lexical clusters are resolved with the manifest-pinned
`sentence-transformers/all-MiniLM-L6-v2`. Scout loads local safetensors only,
with remote code, downloads and telemetry disabled. It embeds one representative
title per lexical cluster. Missing files or invalid vectors fail visibly.

The manifest owns resource ceilings, time windows, vocabularies, aliases and
rounded cosine thresholds. Candidate pairs must share extracted entities or an
exact canonical URL. Peer order is time gap then lexical key, never activity.
Signals use stored titles, URLs and times only; they are conservative heuristics,
not proof of event identity.

Compatible nonempty entity and event-action sets are required for similarity
linking. Numeric, negation, action and entity conflicts veto a link. Reversed
actor roles, passive ambiguity, missing numbers and generic entity pages without
event context remain unresolved. High cosine similarity cannot override a veto.
Inconsistent signals inside a lexical cluster prevent semantic linking without
changing its lexical membership.

Each compared pair records `linked`, `separate` or `unresolved`, with its signals
and reason. Uncompared, uncertain or capacity-excluded clusters remain singletons;
capacity exclusion is not evidence of different events. Complete-link grouping
requires every pair across proposed groups to qualify. A–B and B–C do not imply
A–C. Similarity/key order is deterministic. The smallest persisted trend ID,
then lexical key, determines the group's resolved identity.

### Frozen evidence and replay

Scout claims a unique evaluation slot, freezes complete collection-attempt IDs,
source configurations and source/history health, then resolves outside the write
transaction. It commits one immutable `scout_event_resolutions` record under a
live owner/version fence. The record binds source hash, model/revision/policy,
lexical membership, observation IDs, signals, pair outcomes and final partition.
Embedding hashes/counts are traceability evidence; scoring does not need vectors.

Only a durable resolution can be scored. Replay uses the stored partition and
original evaluation clock, without another encoder call or new configuration.
A crash before resolution commits may repeat local inference on the same frozen
input. Collection completed after input freeze belongs to another evaluation.
Completed observations, resolutions and score snapshots cannot be rewritten.
Exact tables/constraints belong to the [data model](data-model.md#schema-and-record-inventory)
and [SQL](../contracts/application-schema.sql).

### Conservative scoring credit

A resolved event inherits all scoring/eligibility credit from its strongest
lexical constituent: eligible first, then score, breadth, prominence and lexical
key. Other members remain visible with zero scoring credit. Prominence uses
lexical populations. Semantic linking cannot manufacture breadth, growth,
persistence or shortlist eligibility, even if a link is wrong. This deliberately
limits recall: two uncorroborated lexical clusters cannot pass bootstrap merely
because MiniLM links them. Existing selected constituent ownership suppresses a
second initial handoff when a resolved root changes.

## Scoring model — `attention_v3`

Fast sources use the trailing 24 hours; Wikimedia uses its latest completed
report day. Repeated polls do not multiply activity. For source kind `s`:

| Input | Meaning |
| --- | --- |
| Publisher `A_s` | Distinct contributing independence groups in the lexical cluster/window. |
| Wikimedia `A_s` | Sum of distinct article/day pageview rows; repeated reports do not add views. |
| HN `A_s` | Maximum `(101-r)/100 × log2(q+1)` across matching observations; six-decimal rounding. |
| `B_s` | Median activity in valid days among the preceding 14 completed daily windows; ready after seven valid windows. |
| `P_s` | Prominence in the source kind's lexical activity population: `1-(midrank-1)/(N-1)`, or `0.5` for a singleton. Equal activities share midrank. |
| `G_s` | When history-ready, `clamp(log2((A_s+1)/(B_s+1))/2, 0, 1)`; otherwise `0.5 × P_s`, explicitly labeled bootstrap. |
| `R_s` | Strongest contributing source-instance trust × health multiplier for that kind. |

A valid baseline day without matching evidence contributes zero. Missing/degraded
history is excluded, not represented as zero. Source health is current when its
latest complete snapshot is within 1.5 availability intervals with no subsequent
failure. Valid evidence within three intervals can contribute at degraded weight
0.5; current evidence uses 1.0. Unavailable/failed/quota-limited sources do not
contribute. Exact frozen health, observations and baseline days remain inspectable.

Momentum, prominence and reliability are reliability-weighted means of their
source-kind inputs. Breadth is `min(1, independence_groups/3)`; persistence is
`min(1, distinct completed days observed in the last 72 hours/3)`.

```text
score = round(momentum/3 + prominence*2/9 + breadth*2/9
              + persistence/9 + reliability/9, 4)
```

Evidence recency is a persisted diagnostic and ranking tie-breaker, with zero
score weight. Snapshots freeze component inputs, bootstrap status, population
hashes, formula version, selected scoring constituent and excluded observations.
The dashboard reads this evidence; it does not recalculate attention.

## Selection — `shortlist_v2`

The release manifest owns minimum score/reliability and global rolling six-hour
and 24-hour selection caps. An initial selection requires those gates plus
history readiness in at least one contributing kind, or two independent groups
within the scoring lexical cluster. A prior selected identity or owned
constituent prevents duplicate seeding.

Candidates rank by score, breadth, prominence and evidence recency descending,
then stable opportunity identity. Scout commits all snapshots and projections,
rechecks ownership/capacity and creates selected handoffs in one fenced SQLite
transaction. Budget counts use persisted selections at or after each cutoff;
already-committed same-slot selections count. Coverage-identity collisions roll
back the handoff instead of creating a duplicate thread.

Budget-deferred Clusters remain queued and are reconsidered when their opportunity
has current source evidence in another evaluation. There is no age-based queue
expiry, automatic recurrence, cooldown transition or blocked-route recheck.
Selected identities keep their original thread and frozen initial brief; new
snapshots update evidence without reseeding. Human refinement can create another
brief/decision in that thread while retaining original Detection lineage.

## Modification boundaries

Change sources/algorithms through their executable configuration and validators.
Keep versioned immutable evidence interpretable. Tests must protect source
allowlists and metadata bounds, lexical identity, health/baselines, semantic vetoes
and replay, scoring credit, global selection capacity and atomic handoffs.
[Dashboard](dashboard.md) owns evidence presentation; [runtime](runtime.md) owns
polling/claims; [configuration](configuration.md) owns activation and settings.
