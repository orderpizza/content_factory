# System Dashboard

## Purpose

The dashboard is the system-level observability surface for the Content
Factory. It provides one place to understand what the system detected, decided,
produced, rendered, queued, and published.

The existing trend dashboard becomes the `Trend Detection` view within this
larger dashboard. It remains responsible for showing detection evidence,
candidate rankings, lifecycle state, scoring explanations, source health, and
historical observations.

## Views

The dashboard should eventually contain these views:

- **Overview** — current system state, recent activity, failures, and pending work.
- **Trend Detection** — observations, topic snapshots, candidates, scores, and source health.
- **Determination** — candidate evaluations and `ContentJob` decisions.
- **Content Jobs** — pending, running, completed, and failed jobs.
- **Production** — pipeline runs and generated `ContentPackage` records.
- **Visual Assets** — rendered assets and rendering failures.
- **Posting** — queue state, scheduled posts, publication results, and failures.
- **System Health** — process runs, dependency failures, and database health.

## Boundary Rules

The dashboard is read-only during the POC. It reports system state but does not
control detection, determination, pipeline execution, rendering, or posting.
Workflow decisions remain in the owning components.

## Runtime

The local dashboard server renders directly from SQLite on every HTTP request;
it does not depend on a manually generated HTML snapshot. The browser refreshes
every 15 seconds, so changes written by any running module become visible
without restarting the dashboard. On the Mac Mini, load
`scripts/com.contentfactory.dashboard.plist` with launchd alongside the Scout
service so the dashboard starts at login and is restarted if it exits.

The dashboard reads reporting data and workflow state from SQLite. It must not
call module services, depend on private implementation details of individual
modules, or contain their business logic.

Each module owns the meaning of its own status and reporting data. The
dashboard composes those module-level reports into a system-level view.

## POC Scope

The current implementation may continue to expose the trend detection view
first. System-level views should be added as the corresponding POC modules are
implemented. Do not add placeholder workflow controls or complex dashboard
infrastructure before the corresponding system components exist.
