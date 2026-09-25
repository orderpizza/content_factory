"""Closed, curated account identities, archetypes and immutable recipe contracts."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from .visual_art_direction import (
    EXPRESSION_ROLE_DIRECTIONS, AI_TECH_ROLE_DIRECTIONS, PSYCHOLOGY_ROLE_DIRECTIONS,
)

PROMPT_COMPILER_VERSION = "gemini_storyboard_prompt_v6"
RENDERER_CONTRACT_ID = "image_storyboard_paginated_v3"
SELECTOR_VERSION = "deterministic_archetype_selector_v1"
DEFAULT_ARCHETYPE_BY_DOMAIN = {
    "english": "expression_breakdown_v1",
    "ai_tech": "ai_tech_explainer_v1",
    "psychology": "psychology_explainer_v1",
}
EXPRESSION_ROLES = ("hook", "explanation", "explanation", "example", "example", "takeaway")
EXPLAINER_ROLES = ("hook", "explanation", "explanation", "example", "explanation", "takeaway")
EXPRESSION_LABELS = ("ENGLISH EXPRESSIONS", "MEANING", "WHEN TO USE IT", "EXAMPLE", "IN A CONVERSATION", "KEY TAKEAWAY")


def _lines(value: str) -> list[str]:
    return [line.strip(" •-\t") for line in value.splitlines() if line.strip(" •-\t")]


def _word_count(value: str) -> int:
    return len(value.split())


def validate_expression_units(units: list[Mapping[str, Any]]) -> None:
    """Validate registered English subsequences of the accepted teaching grammar."""
    from .content_contract import english_positions
    positions = english_positions(len(units))
    if [u.get('role') for u in units] != [EXPRESSION_ROLES[i] for i in positions]:
        raise ValueError('expression requires its registered content role sequence')
    for unit, position in zip(units, positions):
        if (len(unit['title']) > 120 or len(unit['body']) > 600
            or _word_count(unit['title']) > (5 if position == 0 else 12)
            or len(_lines(unit['title'])) > 2):
            raise ValueError('expression title/body exceeds readable capacity')
        lines = _lines(unit['body'])
        low, high, words, first, later = (
            (1, 5, 20, 20, 20), (1, 5, 60, 35, 18), (3, 4, 56, 14, 14),
            (2, 2, 44, 22, 22), (3, 4, 64, 16, 16), (2, 3, 48, 16, 16))[position]
        if (not low <= len(lines) <= high or _word_count(unit['body']) > words
            or _word_count(lines[0]) > first or any(_word_count(line) > later for line in lines[1:])):
            raise ValueError('expression copy exceeds its readable content capacity')
        if position == 4 and any(not re.fullmatch(r"[^:]{1,40}:\s*\S.*", line) for line in lines):
            raise ValueError('expression dialogue requires three or four concise turns')


@dataclass(frozen=True)
class AccountVisualIdentity:
    """Reusable account art direction only; no geometry, slide grammar or prompt fragments."""
    id: str
    domain: str
    personality: str
    color_behavior: str
    illustration_character: str
    typography_character: str
    whitespace: str
    polish: str
    general_positive_rules: str
    general_negative_rules: str


ACCOUNT_PROFILES = {
    'english': AccountVisualIdentity('o2english_visual_identity_v1', 'english',
        'Friendly premium educational editorial', 'Bold but controlled coherent color',
        'Supporting expressive characters and meaningful icons', 'Strong expression-first hierarchy',
        'Intentional breathing room', 'Human-designed editorial finish',
        'One obvious reading order; teaching comes first; clear visual grouping; '
        'meaningful illustrations support the lesson; restrained highlights and accents',
        'No poster collage, scrapbook, worksheet, art print, dense infographic, PowerPoint '
        'or corporate dashboard aesthetics; no cramped copy, washed-out blobs, thin-line-only scenes, '
        'decorations overlapping text, oversized illustrations, excessive stickers or visual noise'),
    'ai_tech': AccountVisualIdentity('ai_tech_visual_identity_v1', 'ai_tech',
        'Credible accessible technology editorial', 'Restrained contemporary color',
        'Conceptual software and mechanism illustrations', 'Clear technical hierarchy',
        'Generous separation', 'Modern product editorial finish',
        'Make practical implications and limitations equally readable',
        'No cyberpunk, robot stock art, invented screenshots or unrequested provider brands'),
    'psychology': AccountVisualIdentity('psychology_visual_identity_v1', 'psychology',
        'Warm thoughtful evidence-aware education', 'Calm warm controlled color',
        'Relatable people and qualified conceptual metaphors', 'Approachable readable hierarchy',
        'Calm space around observations and qualifications', 'Careful editorial finish',
        'Distinguish observation, inference and alternative explanations',
        'No diagnosis, manipulation imagery, pseudo-clinical evidence or asserted motives'),
}

OVERLAY_PROFILES = {
    'english': {'labels': EXPRESSION_LABELS, 'brand': 'o2_english',
        'cta_namespace': 'expression-footer-cta-v1', 'overlay_version': 'expression_transparent_chrome_v2'},
    'ai_tech': {'labels': ('AI / TECH', 'WHAT CHANGED', 'WHY IT MATTERS', 'USE CASE', 'LIMITS', 'TAKEAWAY'),
        'brand': None, 'cta_namespace': 'ai-tech-footer-cta-v1', 'overlay_version': 'ai_tech_transparent_chrome_v2'},
    'psychology': {'labels': ('PSYCHOLOGY', 'THE CONCEPT', 'WHY IT MAY HAPPEN', 'EXAMPLE', 'WHAT HELPS', 'TAKEAWAY'),
        'brand': None, 'cta_namespace': 'psychology-footer-cta-v1', 'overlay_version': 'psychology_transparent_chrome_v2'},
}


@dataclass(frozen=True)
class SlideGrammar:
    ordinal: int
    role: str
    purpose: str
    composition: str
    visual_mode: str
    title_words: int
    body_words: int
    title_characters: int = 80
    body_characters: int = 360
    min_lines: int = 1
    max_lines: int = 5
    line_words: int = 60


@dataclass(frozen=True)
class Archetype:
    archetype_id: str
    version: int
    domain: str
    account_visual_profile_id: str
    selection_characteristics: tuple[str, ...]
    art_direction: str
    negative_constraints: str
    slides: tuple[SlideGrammar, ...]


_ENGLISH_PURPOSES = ('hook', 'meaning / definition', 'when to use it / use cases',
                     'examples', 'short conversation / dialogue', 'takeaway / reminder')
_PURPOSES = {
    'english': _ENGLISH_PURPOSES,
    'ai_tech': ('hook', 'what changed / what it is', 'why it matters / how it works',
                'practical use / example', 'limitations / caveats', 'takeaway'),
    'psychology': ('observed pattern / hook', 'concept / meaning', 'possible mechanism',
                   'everyday example', 'practical implication', 'takeaway / qualification'),
}


def _archetype(id, domain, traits, direction, compositions, modes, *, compact=False, negative=''):
    roles = EXPRESSION_ROLES if domain == 'english' else EXPLAINER_ROLES
    slides = []
    for i, (role, purpose, composition, mode) in enumerate(zip(roles, _PURPOSES[domain], compositions, modes), 1):
        if domain == 'english':
            # Preserve accepted line-specific English limits; scene copy is tighter.
            title, body, low, high, line = (
                (5, 18 if compact else 20, 1, 5, 20), (12, 60, 1, 5, 35),
                (12, 48 if compact else 56, 3, 4, 12 if compact else 14),
                (12, 36 if compact else 44, 2, 2, 18 if compact else 22),
                (12, 56 if compact else 64, 3, 4, 14 if compact else 16),
                (12, 42 if compact else 48, 2, 3, 14 if compact else 16),
            )[i-1]
            slides.append(SlideGrammar(i, role, purpose, composition, mode, title, body,
                                      120, 600, low, high, line))
        else:
            slides.append(SlideGrammar(i, role, purpose, composition, mode, 10,
                                      30, body_characters=280, max_lines=3, line_words=16))
    return Archetype(id, 1, domain, ACCOUNT_PROFILES[domain].id, tuple(traits), direction,
                     negative, tuple(slides))


ARCHETYPES = {a.archetype_id: a for a in (
    _archetype('expression_breakdown_v1', 'english', ('general',),
        'Premium expression-centered education, supporting illustrations, grouped cards, examples and dialogue.',
        EXPRESSION_ROLE_DIRECTIONS, ('editorial',)*6),
    _archetype('expression_story_scene_v1', 'english', ('human_interaction', 'dialogue', 'everyday_context'),
        'Teach expressions through human interaction and situational storytelling; less dependence on generic cards.',
        ('Hero expression with a supporting human scene.', 'Definition with a simple visual metaphor.',
         'Sequence of everyday situations.', 'Two distinct practical scenes.',
         'Character conversation with clear speaker separation.', 'Clean recap with a restrained illustration.'),
        ('human_scene', 'metaphor', 'human_scene', 'paired_scenes', 'dialogue', 'editorial'), compact=True),
    _archetype('expression_cards_v1', 'english', ('usage_distinctions', 'multiple_uses', 'abstract_meaning'),
        'Typography-led explanation, controlled color blocking, structured cards and icon-supported grouping.',
        ('Oversized expression and bold type.', 'Structured definition card.',
         'Three or four compact situation cards.', 'Paired example cards.',
         'Typography-forward conversation with separate speakers.', 'Compact reminder card.'),
        ('typography', 'cards', 'cards', 'cards', 'dialogue', 'cards')),
    _archetype('ai_tech_explainer_v1', 'ai_tech', ('general',),
        'General-purpose technology editorial explainer.', AI_TECH_ROLE_DIRECTIONS, ('editorial',)*6),
    _archetype('ai_tech_product_ui_v1', 'ai_tech', ('product_central', 'capabilities', 'software_use_cases'),
        'Interface-inspired conceptual panels, feature callouts and practical product workflows.',
        ('Topic headline with a conceptual product panel.', 'Feature callouts in a conceptual interface.',
         'Before and after capability comparison.', 'Product workflow in bounded conceptual panels.',
         'Constraints and availability in prominent capability cards.', 'Compact practical product summary.'),
        ('conceptual_ui',)*6, compact=True,
        negative='Invented UI is conceptual illustration, never an authentic screenshot or factual evidence. No unrequested provider branding.'),
    _archetype('ai_tech_system_diagram_v1', 'ai_tech', ('mechanism', 'components', 'process_steps'),
        'Clean conceptual system explanation using steps, relationships and input → process → output.',
        ('Headline with one simple system relationship.', 'Identify conceptual inputs and outputs.',
         'Ordered mechanism with arrows between interacting parts.', 'Trace one supplied example through the flow.',
         'Show constraints beside the affected step without inventing failure claims.', 'Simplified process recap.'),
        ('process',)*6, compact=True, negative='No cyberpunk or meaningless network-node decoration.'),
    _archetype('psychology_explainer_v1', 'psychology', ('general',),
        'Evidence-aware behavioral editorial education.', PSYCHOLOGY_ROLE_DIRECTIONS, ('editorial',)*6),
    _archetype('psychology_human_scenario_v1', 'psychology', ('social_context', 'human_reaction', 'everyday_scenario'),
        'Everyday human interactions, paired reactions and scenario-led behavioral explanation.',
        ('Recognizable observed human moment.', 'Scene plus qualified interpretation, separate from observation.',
         'Paired possible reactions; keep uncertainty visible.', 'Everyday interaction in the supplied hypothetical scenario.',
         'Optional practical response in a conversational scene.', 'Calm recap preserving qualification and alternatives.'),
        ('human_scene',)*6, compact=True, negative='No inferred diagnoses, asserted motives or exaggerated emotional faces.'),
    _archetype('psychology_concept_cards_v1', 'psychology', ('cognitive_concept', 'alternatives', 'observation_vs_interpretation'),
        'Structured cognitive education: contrasting explanations and observation → thought → response.',
        ('Concept headline with restrained metaphor.', 'Separate observation and interpretation cards.',
         'Qualified behavior-to-thought-to-response diagram.', 'Paired alternative explanations of the example.',
         'Grouped practical responses without prescriptive clinical advice.', 'Summary card with equally visible qualification.'),
        ('cards', 'comparison', 'process', 'comparison', 'cards', 'cards'),
        negative='Qualifications must remain visible; conceptual relationships are not proof or diagnosis.'),
)}


def grammar_for_unit(archetype, unit, index, total=6):
    if archetype.domain == 'english':
        from .content_contract import english_positions
        return archetype.slides[english_positions(total)[index]]
    if index < len(archetype.slides) and archetype.slides[index].role == unit['role']:
        return archetype.slides[index]
    candidates = [s for s in archetype.slides if s.role == unit['role']]
    return candidates[index % len(candidates)]


def archetype_contract(archetype_id):
    try:
        return asdict(ARCHETYPES[archetype_id])
    except (KeyError, TypeError) as error:
        raise ValueError('unavailable archetype') from error


def profile_fingerprint():
    value = {'accounts': {k: asdict(v) for k, v in ACCOUNT_PROFILES.items()},
             'archetypes': {k: asdict(v) for k, v in ARCHETYPES.items()}, 'overlays': OVERLAY_PROFILES}
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_archetype_units(units, archetype_id):
    from .visual_explainers import validate_domain_units
    a = ARCHETYPES[archetype_id]
    if not isinstance(units, list)  or any(not isinstance(u, Mapping) for u in units):
        raise ValueError('archetype requires bounded visual units')
    validate_domain_units(units, a.domain, strict_english=True)
    for index, unit in enumerate(units):
        slide = grammar_for_unit(a, unit, index, len(units))
        for field, words, chars in (('title', slide.title_words, slide.title_characters),
                                    ('body', slide.body_words, slide.body_characters)):
            if len(unit[field].split()) > words or len(unit[field]) > chars:
                raise ValueError(f'archetype slide {slide.ordinal} {field} exceeds capacity')
        lines = _lines(unit['body'])
        if not slide.min_lines <= len(lines) <= slide.max_lines or any(len(s.split()) > slide.line_words for s in lines):
            raise ValueError(f'archetype slide {slide.ordinal} exceeds line capacity')


def active_recipe(pipeline_id, roles=None, *, account='fixture', archetype_id=None, selection=None):
    a = ARCHETYPES[archetype_id or DEFAULT_ARCHETYPE_BY_DOMAIN[pipeline_id]]
    if a.domain != pipeline_id or (roles is not None and roles != [s.role for s in a.slides]):
        raise ValueError('archetype domain/grammar mismatch')
    if selection is None:
        # Offline fixture construction only. Runtime always supplies audited selection.
        from .archetype_selection import select_archetype
        _, selection = select_archetype({}, pipeline_id, [])
        if a.archetype_id != DEFAULT_ARCHETYPE_BY_DOMAIN[pipeline_id]:
            raise ValueError('specialized recipes require selector provenance')
    return {'schema_version': 'visual_recipe_v5', 'account': account,
            'account_visual_profile_id': a.account_visual_profile_id,
            'archetype_id': a.archetype_id, 'archetype_version': a.version,
            'profile_fingerprint': profile_fingerprint(),
            'prompt_compiler_version': PROMPT_COMPILER_VERSION,
            'renderer_contract_id': RENDERER_CONTRACT_ID,
            'overlay_profile_id': OVERLAY_PROFILES[pipeline_id]['overlay_version'],
            'selection': selection}


def validate_recipe(value, *, production=False):
    expected = {'schema_version', 'account', 'account_visual_profile_id', 'archetype_id', 'archetype_version',
                'profile_fingerprint', 'prompt_compiler_version', 'renderer_contract_id', 'overlay_profile_id', 'selection'}
    if not isinstance(value, Mapping) or set(value) != expected or value['schema_version'] != 'visual_recipe_v5':
        raise ValueError('visual recipe has an invalid closed shape')
    for field in expected - {'selection', 'archetype_version'}:
        if not isinstance(value[field], str):
            raise ValueError('visual recipe identifiers must be strings')
    a = ARCHETYPES.get(value['archetype_id'])
    if a is None or type(value['archetype_version']) is not int or value['archetype_version'] != a.version:
        raise ValueError('unavailable archetype version')
    if not isinstance(value['account'], str) or not value['account'].strip():
        raise ValueError('recipe account is missing')
    from .archetype_selection import validate_selection
    validate_selection(value['selection'], a.domain, a.archetype_id)
    if dict(value) != active_recipe(a.domain, account=value['account'], archetype_id=a.archetype_id, selection=value['selection']):
        raise ValueError('visual recipe identity/compiler/renderer/overlay mismatch')
    return dict(value)


def validate_recipe_roles(recipe, roles):
    a = ARCHETYPES[recipe['archetype_id']]
    if a.domain != 'english':
        from .visual_explainers import validate_dynamic_roles
        validate_dynamic_roles(roles)
        return
    from .content_contract import english_positions
    if roles != [a.slides[i].role for i in english_positions(len(roles))]:
        raise ValueError('visual recipe package roles do not match archetype')
