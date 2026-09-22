# Posting and delivery boundary

**Owner:** Preserved generic downstream authorization, delivery evidence and R2 staging.

The overall architecture includes review → posting/delivery → external delivery.
Current development and acceptance end at review-ready slides visible through
the dashboard. There is no active posting provider, provider configuration CLI,
public posting command or delivery worker composition.

The existing generic downstream tables remain to avoid unnecessary schema churn:
PostRequest captures exact reviewed content/asset hashes; PostRecord and attempts
track delivery; publication resources and cleanup tasks track staged objects;
reconciliation requests/checks preserve uncertain outcomes. Review acceptance
alone never authorizes public delivery. Dormant store methods and injected fake
adapter tests retain per-destination authorization, cadence, live-claim fencing,
final-send markers and no automatic repost after uncertain publication.

`workflow.delivery` preserves generic delivery orchestration with an empty
adapter registry by default. Provider reconciliation reports unavailable until
explicitly supplied by an implementation; it does not infer success. Inactive
configuration records use an `unimplemented` adapter marker, not provider API
fields. They cannot make the upstream catalog deliverable.

R2 remains a transient media relay, not canonical storage. Its preserved helper
checks exact bytes/hashes, uses attempt-scoped keys, verifies public fetches and
records cleanup separately from publication. R2 cleanup cannot undo a public
post. No current workflow command stages media or calls a posting provider.

[Data model](data-model.md) owns persisted identity and
[reliability](reliability.md) owns uncertainty and storage admission.
