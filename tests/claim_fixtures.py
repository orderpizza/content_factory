"""Compile invented offline prose fixtures into the current reference contract."""
from workflow.gemini_generation import semantic_values


def register_fixture_semantics(content):
    claims = content['claims']
    texts = {c['text']: c['claim_id'] for c in claims}
    for path, text in list(semantic_values(content)):
        if isinstance(text, dict):
            continue
        if text not in texts:
            claim_id = 'fixture.semantic.' + str(len(claims))
            claims.append(dict(claim_id=claim_id, text=text, claim_kind='generated_example',
                               evidence_reference_ids=[], qualification='Invented offline fixture.'))
            texts[text] = claim_id
        parts = path.split('.')
        parent = content
        for key in parts[:-1]: parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        parent[key] = {'claim_id': texts[text]}
    return content


def line_response(response):
    for unit in response['visual_units']:
        if 'body' in unit:
            unit['body_lines'] = unit.pop('body').splitlines()
    return response


def proposal_response(plan):
    from workflow.editorial_planning import PROPOSAL_SCHEMA
    from copy import deepcopy
    result = {k: deepcopy(v) for k, v in plan.items() if k in PROPOSAL_SCHEMA['properties']}
    keys = PROPOSAL_SCHEMA['properties']['candidates']['items']['properties']
    result['candidates'] = [{k: v for k, v in c.items() if k in keys} for c in result['candidates']]
    return result
