"""Explicit invented semantic registry for offline fixtures, never production repair."""
from workflow.gemini_generation import semantic_values


def register_fixture_semantics(content):
    claims = [c for c in content['claims'] if not c['claim_id'].startswith('fixture.semantic.')]
    texts = {c['text'] for c in claims}
    for path, text in semantic_values(content):
        if text not in texts:
            claims.append(dict(claim_id='fixture.semantic.' + str(len(claims)), text=text,
                               claim_kind='generated_example', evidence_reference_ids=[],
                               qualification='Invented offline fixture; not factual evidence.'))
            texts.add(text)
    content['claims'] = claims
    return content
