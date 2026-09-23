"""Semantic, claim-referenced cues; no model-authored prompt fragments."""
CUE_EMPHASIS = ('situation', 'contrast', 'sequence', 'qualification', 'takeaway')
VISUAL_CUES_SCHEMA = {
    'type': 'array', 'maxItems': 6, 'items': {
        'type': 'object', 'additionalProperties': False,
        'required': ['slide', 'subject_claim_id', 'semantic_emphasis', 'participants_count'],
        'properties': {
            'slide': {'type': 'integer', 'minimum': 1, 'maximum': 6},
            'subject_claim_id': {'type': 'string', 'minLength': 1, 'maxLength': 120},
            'semantic_emphasis': {'type': 'string', 'enum': list(CUE_EMPHASIS)},
            'participants_count': {'type': 'integer', 'minimum': 0, 'maximum': 4},
        },
    },
}


def validate_cues(value, allowed_claims, units):
    if not isinstance(value, list) or len(value) > 6:
        raise ValueError('visual cues must be a bounded list')
    seen = set()
    for c in value:
        if not isinstance(c, dict) or set(c) != set(VISUAL_CUES_SCHEMA['items']['required']):
            raise ValueError('visual cue has an invalid closed shape')
        if type(c['slide']) is not int or not 1 <= c['slide'] <= 6 or c['slide'] in seen:
            raise ValueError('visual cue slide must be unique and in range')
        seen.add(c['slide'])
        if (not isinstance(c['subject_claim_id'], str) or c['subject_claim_id'] not in allowed_claims
            or c['subject_claim_id'] not in units[c['slide']-1]['claim_ids']):
            raise ValueError('visual cue must reference a canonical claim mapped to its slide')
        if c['semantic_emphasis'] not in CUE_EMPHASIS or type(c['participants_count']) is not int or not 0 <= c['participants_count'] <= 4:
            raise ValueError('unsupported semantic cue')
    return value
