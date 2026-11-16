# English pilot review — blank reusable template

Copy into the ignored run/attempt directory; never fill this tracked template
with run evidence. Follow [the rubric](../../docs/testing.md#english-pilot-human-review).
Blank = unassessed. N/A needs a reason. Human decisions: pass / needs edit / reject.

## Identity and reproducibility

- Run ID / case ID / attempt / revision parent:
- Case file SHA-256 / Git revision / rubric revision:
- Reviewer / second reviewer / reviewed at (ISO-8601 with timezone):
- Level / lesson family / learning goal / target:
- Positive carousel or clarification control:
- Model IDs / endpoint / SDK / prompt, schema, compiler, policy versions:
- Price snapshot fingerprint / rates, currency and date/source:
- Package hash / ReviewRequest ID / manifest path / final asset hashes:
- Artifact paths (input, canonical, adaptation, raw boards, final slides, ledger):
- Final slide count / initial board partition / actual image calls / archetype:
- Device / viewport CSS width / full-resolution comparison completed:
- Automatic result / unresolved findings / missing artifacts:

## Human scores and evidence

Use 0/1/2 for positive samples; use N/A with reason for the control.

| Dimension | Score | Evidence (slide/claim/artifact and observation) |
| --- | --- | --- |
| Meaning correctness | | |
| Naturalness | | |
| Register and nuance | | |
| Level and comprehension | | |
| Semantic fidelity | | |
| Visual readability | | |
| Typo/text fidelity | | |
| Slide count and sequence | | |
| Coherence | | |
| Distinctiveness | | |
| Actionability | | |

Control only: clarification question / helpfulness / brief absent / downstream
work absent / evidence:

| Failure code | Severity | Origin stage | Slide/claim | Expected versus observed | Required change |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

- First decision / rationale (before edits):
- Second assessment / disagreements / adjudication:
- Edit scope / changed units / estimated edit minutes:
- First-review minutes / actual active edit minutes / re-review minutes:
- Revision count / regeneration calls / linked revised attempt:
- Final decision / rationale / exact newly reviewed hashes:
- Missing review or incomplete output reason:

## Accounting (all invocations, including failures)

- Ledger export path / invocation count / text calls / image calls:
- Observed input tokens / observed output tokens by text and image phase:
- Missing-usage invocation IDs (unknown, not zero):
- Settled USD / active reservation USD / uncertain hold USD:
- Cost basis / unresolved or disputed accounting:
- Operator hourly rate if supplied / operator cost (otherwise unknown):
- Publication receipt / published count / cost per published: N/A for Phase 2A/2B.

## Campaign roll-up (one copy at campaign root)

- Frozen plan and authorized cumulative ceilings / start and end / run IDs:
- Planned positive/control attempts / started / completed / skipped (reasons):
- First-pass / needs-edit / reject / unreviewed counts by level and family:
- Finally approved distinct lessons / edit rounds / reviewer disagreements:
- Review and edit minutes: median, range, n / total operator minutes:
- Total text/image calls and observed tokens / missing-usage count:
- Settled USD / active USD / uncertain USD / known accounting completeness:
- Model USD, tokens and image calls per approved (undefined if zero approvals):
- Operator and combined cost per approved (unknown without hourly rate):
- Gate outcomes / stop condition / owner-adjusted targets with rationale:
- Evidence limitations / next experiment / architectural review decision:
