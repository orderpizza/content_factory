"""Content pagination and resolved copy capacity; independent of render-board packing."""
from dataclasses import asdict
import re
import unicodedata

VERSION = 'resolved_content_contract_v2'
ENGLISH_POSITIONS = {4: (0, 1, 4, 5), 5: (0, 1, 3, 4, 5), 6: (0, 1, 2, 3, 4, 5)}


def english_positions(total):
    if total not in ENGLISH_POSITIONS:
        raise ValueError('English content requires a registered 4, 5 or 6 slide sequence')
    return ENGLISH_POSITIONS[total]


def english_count(canonical):
    requested = canonical.get('requested_slide_count')
    if requested is not None:
        english_positions(requested)
        return requested
    # Meaning and dialogue always teach the subject; multiple examples and use
    # contexts add distinct semantic units. No padding to match an image grid.
    payload = canonical.get('domain_payload', {})
    if len(payload.get('usage_notes', [])) >= 3:
        return 6
    if len(canonical.get('examples', [])) >= 2:
        return 5
    return 4


def resolve_content_contract(canonical, archetype_id):
    from .active_visual_profiles import ARCHETYPES, EXPRESSION_LABELS
    a = ARCHETYPES[archetype_id]
    base = dict(version=VERSION, domain=a.domain, archetype_id=archetype_id)
    requested = canonical.get('requested_slide_count')
    if requested is not None and (type(requested) is not int or not (4 <= requested <= (6 if a.domain == 'english' else 14))):
        raise ValueError(f'No compatible {a.domain} archetype for requested {requested} slides; supported range is 4–{6 if a.domain == "english" else 14}')
    if a.domain != 'english':
        return dict(**base, minimum_units=requested or 4, maximum_units=requested or 14,
                    sequence='hook, explanation/example interiors (at least one each), takeaway',
                    role_capacities=[dict(role=s.role, purpose=s.purpose, title_words=s.title_words,
                        body_words=s.body_words, title_characters=s.title_characters,
                        body_characters=s.body_characters, title_lines=2, min_lines=s.min_lines,
                        max_lines=s.max_lines, line_words=s.line_words) for s in a.slides])
    total = english_count(canonical)
    slides = []
    for ordinal, position in enumerate(english_positions(total), 1):
        s = a.slides[position]
        capacity = {k: v for k, v in asdict(s).items() if k not in {'ordinal', 'composition', 'visual_mode'}}
        capacity.update(ordinal=ordinal, title_lines=2, chrome_label=EXPRESSION_LABELS[position],
                        requires_target=position in {0, 4},
                        target_fields=['body'] if position == 4 else ['title', 'body'], dialogue=position == 4,
                        first_line_words=min(s.line_words, 35) if position == 1 else s.line_words,
                        later_line_words=18 if position == 1 else s.line_words)
        slides.append(capacity)
    return dict(**base, minimum_units=total, maximum_units=total,
                target=canonical['domain_payload']['target'], slides=slides)


def normalized_text(text):
    return ' '.join(re.findall(r"\w+", unicodedata.normalize('NFKC', text).casefold()))


REDUNDANT_TITLES = {
    'what does it mean', 'example usage', 'english expressions', 'meaning', 'what it means', 'when to use it',
    'real life examples', 'examples', 'example', 'in conversation',
    'in a conversation', 'key takeaway', 'takeaway',
}


class CapacityError(ValueError):
    def __init__(self, slide, field, rule, actual, limit):
        import json
        self.diagnostic = dict(slide=slide, field=field, rule=rule, actual=actual, limit=limit)
        super().__init__(json.dumps(self.diagnostic, sort_keys=True))


def validate_capacity(unit, slide, ordinal):
    lines = unit.get('body_lines', unit['body'].splitlines())
    if 'body_lines' in unit and unit['body'] != '\n'.join(lines):
        raise ValueError('render body differs from validated body_lines')
    for field, count, minimum, maximum in (
        ('body_lines', len(lines), slide['min_lines'], slide['max_lines']),
        ('title', len(unit['title'].splitlines()), 1, slide.get('title_lines', 2)),
    ):
        if count < minimum: raise CapacityError(ordinal, field, 'min_lines', count, minimum)
        if count > maximum: raise CapacityError(ordinal, field, 'max_lines', count, maximum)
    for field in ('title', 'body'):
        for rule, actual, limit in [('max_words', len(unit[field].split()), slide[field+'_words']),
                                    ('max_characters', len(unit[field]), slide[field+'_characters'])]:
            if actual > limit: raise CapacityError(ordinal, field, rule, actual, limit)
    for index, line in enumerate(lines):
        limit = slide.get('first_line_words' if index == 0 else 'later_line_words', slide['line_words'])
        if len(line.split()) > limit:
            raise CapacityError(ordinal, f'body_lines[{index}]', 'max_words', len(line.split()), limit)
    if slide.get('dialogue'):
        if any(not re.fullmatch(r'[^:]{1,40}:\s*\S.*', line) for line in lines):
            raise ValueError(f'slide {ordinal}: dialogue requires named speaker turns')
        speakers = [line.split(':', 1)[0].strip() for line in lines]
        if len(set(speakers)) < 2 or any(a == b for a, b in zip(speakers, speakers[1:])):
            raise ValueError(f'slide {ordinal}: teaching dialogue requires alternating distinct speakers')


def validate_content_contract(units, contract):
    if not contract['minimum_units'] <= len(units) <= contract['maximum_units']:
        raise CapacityError(0, 'visual_units', 'unit_count', len(units), [contract['minimum_units'], contract['maximum_units']])
    for ordinal, unit in enumerate(units, 1):
        slide = (contract['slides'][ordinal-1] if 'slides' in contract else
                 next(s for s in contract['role_capacities'] if s['role'] == unit['role']))
        validate_capacity(unit, slide, ordinal)
        if unit['role'] != slide['role']:
            raise ValueError('content role differs from the resolved sequence')
        if slide.get('requires_target') and (' '+normalized_text(contract['target'])+' ') not in (' '+normalized_text(' '.join(unit[field] for field in slide['target_fields']))+' '):
            raise ValueError('designated hero/dialogue text must contain the target expression')
        if contract['domain'] == 'english' and normalized_text(unit['title']) in REDUNDANT_TITLES:
            raise ValueError('section labels belong to deterministic chrome; use a lesson-specific title')
    from .active_visual_profiles import validate_archetype_units
    validate_archetype_units(units, contract['archetype_id'])


def _polarity(text):
    words = normalized_text(text.replace("n't", ' not')).split()
    return tuple(w for w in words if w not in {'not', 'never'}), any(w in {'not', 'never'} for w in words)


def semantic_qa(units, canonical, contract, public_text='', public_claim_ids=()):
    """Known deterministic failures only; not a claim of general semantic grading."""
    validate_content_contract(units, contract)
    claims = {c['claim_id']: c for c in canonical['claims']}
    mapped = set(public_claim_ids)
    for unit in units:
        if claims and not unit['claim_ids']:
            raise ValueError('public slide assertions require canonical claim mappings')
        mapped.update(unit['claim_ids'])
        if not set(unit['claim_ids']) <= claims.keys():
            raise ValueError('semantic QA found an unknown claim mapping')
        for line in (unit['title']+'\n'+unit['body']).splitlines():
            signature, negative = _polarity(line)
            for claim_id in unit['claim_ids']:
                original, original_negative = _polarity(claims[claim_id]['text'])
                if signature == original and negative != original_negative:
                    raise ValueError('semantic QA found an explicit polarity contradiction')
    if not mapped <= claims.keys():
        raise ValueError('semantic QA found unknown public claim mapping')
    if not set(canonical.get('required_public_claim_ids', [])) <= mapped:
        raise ValueError('semantic QA requires required public teaching claims to be represented')
    # The same identifiable negation error can occur in the caption.
    for sentence in re.split(r'[.!?\n]', public_text):
        signature, negative = _polarity(sentence)
        for claim_id in public_claim_ids:
            original, original_negative = _polarity(claims[claim_id]['text'])
            if signature == original and negative != original_negative:
                raise ValueError('semantic QA found a caption polarity contradiction')
    return {'version': 'pre_render_semantic_qa_v2', 'outcome': 'passed',
            'checks': ['content_contract', 'target_positions', 'dialogue_structure', 'claim_coverage', 'literal_polarity'],
            'scope': 'deterministic checks only; naturalness and semantic entailment require human review'}
