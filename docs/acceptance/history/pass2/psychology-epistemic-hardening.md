# Psychology Epistemic Hardening

## Decision

**Pass 2 is not closed. Do not begin Pass 3 visual acceptance.**

The targeted live campaign validates substantial improvement in canonical
generation, including use of nullable `possible_mechanism` where the frozen
observation establishes no explanation. It does not establish the required
canonical-to-adaptation invariant: one successful adaptation strengthened a
scenario-bound observation into an unsupported frequency claim.

## Scope and evidence

The targeted `psychology_hardening` profile ran against the current production
prompt and `canonical_content_v2` contract. It contains ten direct Psychology
Generation observations and five Generation-to-Adaptation chains. It made 19
text calls, had an estimated cost of $0.092174, and made zero image calls.
The run workspace is `data/acceptance/20260924T133609-5a3b485d/`.

Eleven cases completed their requested production handoffs. Three failures were
provider `504 DEADLINE_EXCEEDED` outcomes; they are not semantic results. One
adaptation failed local slide-capacity validation, also separate from semantic
quality.

## Manual review

The ten direct scenarios cover unfamiliar-group hesitation, meeting-size
participation, delayed replies, deadline-near work, eye contact, workplace
disagreement, reaction checking, time alone, group preference, and continued
option comparison. Usable canonicals consistently distinguished the supplied
observation from possible explanations, retained alternatives, avoided diagnosis,
and used `possible_mechanism: null` when no mechanism was warranted. No repeated
canonical pattern asserted a private motive, diagnosis, or population-level
frequency as a fact.

Two Generation-to-Adaptation chains completed. The group-preference adaptation
retained visible uncertainty and alternatives. The unfamiliar-group adaptation
did not: its canonical described one person who *might* be observed speaking
less, while its first visual unit said, “A person **often** speaks less during
their first meeting with an unfamiliar group.” That changes a scenario-bound
observation into a general frequency claim. Its caption also added a practical
interpretation that was not established by the observation.

## Classification

| Finding | Classification | Result |
| --- | --- | --- |
| Nullable mechanism used by usable canonicals | Production prompt/schema improvement | Supports the Generation correction |
| Three 504s | Provider/transport | Not semantic failures; no blind retry |
| One over-capacity adaptation | Contract/capacity | Not an epistemic result |
| “often speaks less” adaptation copy | Adaptation certainty strengthening | Closure-blocking production defect |

## Required next step

Correct the adaptation-stage strengthening defect, then run a fresh small
Generation-to-Adaptation campaign and inspect every successful pair directly.
Closure requires that adapted copy preserve scenario scope, uncertainty,
alternatives, and causal strength without adding a population frequency or a
hidden explanation. Image calls must remain zero until this text boundary is
accepted.
