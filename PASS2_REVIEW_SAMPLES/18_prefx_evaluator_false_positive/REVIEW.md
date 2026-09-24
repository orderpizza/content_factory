# Failure review

- Source: `20260924T080135-649be4bd`, `stage_generation_ai_scope`, attempt 6
- Configuration: PRE-FIX evaluator; production-shaped generation configuration
- Original acceptance status: FAIL plus WARN
- Selected because: the report identifies it as an AI-scope literal-guard false positive.

The canonical repeatedly describes a hypothetical workflow and declares no availability. The FAIL is solely `canonical_term_missing`, while the remaining WARN calls for a human scope review. The later final rerun contains no such FAIL, so the existing report’s evaluator-defect classification is supported.
