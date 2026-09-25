# Failure review

- Source: `20260924T083654-fffdbca1`, `stage_generation_ai_scope`, attempt 3
- Configuration: FINAL-CONFIGURATION
- Original acceptance status: ERROR
- Selected because: final focused-rerun Generation failure with fixture handoffs retained.

The stage failed before a usable canonical was persisted, so there is no generated content to judge. The generic `stage_execution_failed` evidence does not expose a transport status in the sanitised artifact, so this bundle does not claim 429 versus 504 for this attempt.
