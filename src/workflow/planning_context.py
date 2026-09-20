"""Deterministic model view of frozen evidence, without repeated polling rows."""
from copy import deepcopy

MAX_EVIDENCE_REPRESENTATIVES = 24


def model_context(snapshot):
    """Keep frozen records intact; disclose counts when selecting representatives.

    Latest observation per lexical cluster/source/credit state is enough to
    interpret a topic. Hundreds of repeated rank samples are scoring evidence,
    not hundreds of independent editorial sources.
    """
    value = deepcopy(snapshot)

    def project(item):
        if not isinstance(item, dict):
            return
        evidence = item.get('evidence')
        if item.get('kind') == 'selected_trend' and isinstance(evidence, list):
            representatives = {}
            for row in sorted(evidence, key=lambda e: e.get('observation_id', 0)):
                key = (row.get('lexical_key'), row.get('source'), row.get('contributing'))
                representatives[key] = row
            rows = sorted(representatives.values(), key=lambda e: (not bool(e.get('contributing')), e.get('source',''), e.get('lexical_key',''), e.get('observation_id',0)))
            item['evidence'] = rows[:MAX_EVIDENCE_REPRESENTATIVES]
            item['evidence_selection'] = {
                'policy': 'latest_per_lexical_source_credit',
                'total_observations': len(evidence),
                'representative_groups': len(rows),
                'included': len(item['evidence']),
                'omitted': len(evidence)-len(item['evidence']),
                'full_evidence': 'immutable source snapshot; available in dashboard',
            }
        for child in item.values():
            if isinstance(child, dict):
                project(child)

    project(value)
    return value
