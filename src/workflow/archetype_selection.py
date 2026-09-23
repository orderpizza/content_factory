"""Auditable field-aware semantic scoring; no provider calls or random rotation."""
import re
from collections import Counter
from .active_visual_profiles import ARCHETYPES, DEFAULT_ARCHETYPE_BY_DOMAIN, SELECTOR_VERSION

HISTORY_LIMIT = 8
# Each signal is bounded once, regardless of repeated keywords or copy length.
SIGNAL_WEIGHTS = {
    'human_interaction': 4, 'dialogue': 3, 'everyday_context': 3,
    'usage_distinctions': 4, 'multiple_uses': 3, 'abstract_meaning': 3,
    'product_central': 4, 'capabilities': 3, 'software_use_cases': 3,
    'mechanism': 4, 'components': 3, 'process_steps': 3,
    'social_context': 4, 'human_reaction': 3, 'everyday_scenario': 3,
    'cognitive_concept': 4, 'alternatives': 3, 'observation_vs_interpretation': 3,
}


def _text(value):
    if isinstance(value, list):
        return ' '.join(_text(v) for v in value)
    return value.casefold() if isinstance(value, str) else ''


def _has(value, pattern):
    return bool(re.search(r'\b(?:' + pattern + r')\b', _text(value)))


def semantic_signals(canonical, domain):
    p = canonical.get('domain_payload', {})
    examples = canonical.get('examples', [])
    points = canonical.get('key_points', [])
    if domain == 'english':
        situations = [p.get('plain_meaning'), p.get('usage_notes', []), examples]
        return {
            'human_interaction': _has(situations, r'conversation|coworkers?|friends?|meeting|people|team|interact\w*|speak|listen|discuss\w*'),
            'dialogue': any(re.search(r'\b[A-Z][\w ]{0,15}:', s) for s in examples) or _has(situations, r'dialogue|reply|respond|speaker|ask\w*|told|said'),
            'everyday_context': _has(situations, r'office|school|home|party|class|dinner|work|meeting|group|restaurant'),
            'usage_distinctions': len(p.get('avoid_misuse', [])) >= 2 or _has([p.get('nuance'), p.get('usage_notes', [])], r'contrast|versus|distinguish|difference|whereas|unlike|rather than'),
            'multiple_uses': len(p.get('usage_notes', [])) >= 3,
            'abstract_meaning': _has([p.get('plain_meaning'), p.get('nuance')], r'abstract|degree|certainty|probability|hypothetical|figurative|nuance|intensity'),
        }
    if domain == 'ai_tech':
        mechanism = [p.get('change_summary'), points]
        return {
            'product_central': _has([p.get('product_or_feature'), p.get('change_summary')], r'product|feature|release|update|assistant|editor|software|app|api|tool'),
            'capabilities': len(p.get('capabilities', [])) >= 2,
            'software_use_cases': _has(p.get('use_cases', []), r'code|coding|draft\w*|document\w*|interface|user|app|software|api|developer'),
            'mechanism': _has(mechanism, r'how|mechanism|process|protocol|architecture|pipeline|workflow|retriev\w*|routing'),
            'components': _has(mechanism, r'component\w*|agent|tool|index|database|server|client|input|output') and len(points) >= 3,
            'process_steps': _has(mechanism, r'then|first|next|step\w*|sequence|flows?|through|passes?|sends?|returns?'),
        }
    if domain == 'psychology':
        return {
            'social_context': _has([p.get('context'), p.get('observed_behavior')], r'social|friend\w*|colleague\w*|partner\w*|relationship\w*|group|team|meeting|conversation'),
            'human_reaction': _has(p.get('observed_behavior'), r'react\w*|respond\w*|hesitat\w*|silence|silent|avoid\w*|interrupt\w*|withdraw\w*|disagree\w*'),
            'everyday_scenario': _has(p.get('example'), r'meeting|home|work|friend\w*|family|school|conversation|colleague\w*'),
            'cognitive_concept': _has([p.get('concept'), p.get('possible_mechanism')], r'bias|cognitive|attention|memory|attribution|belief|perception|interpretation'),
            'alternatives': len(p.get('alternative_explanations', [])) >= 3,
            'observation_vs_interpretation': _has([p.get('concept'), p.get('possible_mechanism'), points], r'interpretation|inference|versus|distinguish|alternative|comparison'),
        }
    raise ValueError('unsupported domain')


def _winner(candidates, domain):
    eligible = [c for c in candidates if c['eligible']]
    return min(eligible, key=lambda c: (-c['selection_score'], c['archetype_id'] != DEFAULT_ARCHETYPE_BY_DOMAIN[domain], c['archetype_id']))


def select_archetype(canonical, domain, history):
    signals = semantic_signals(canonical, domain)
    counts = Counter(h['archetype_id'] for h in history)
    candidates = []
    for a in ARCHETYPES.values():
        if a.domain != domain:
            continue
        reasons = [s for s in a.selection_characteristics if signals.get(s)]
        baseline = a.archetype_id == DEFAULT_ARCHETYPE_BY_DOMAIN[domain]
        fit = 5 if baseline else sum(SIGNAL_WEIGHTS[s] for s in reasons)
        penalty = min(1.0, counts[a.archetype_id] * 0.25)
        candidates.append({'archetype_id': a.archetype_id, 'fit_score': fit,
            'recent_use_penalty': penalty, 'selection_score': fit - penalty,
            'eligible': baseline or fit >= 6, 'reason_codes': ['baseline_applicability'] if baseline else reasons})
    winner = _winner(candidates, domain)
    selection = {'strategy': SELECTOR_VERSION, 'history': history, 'candidates': candidates,
                 'fit_score': winner['fit_score'], 'recent_use_penalty': winner['recent_use_penalty'],
                 'reason_codes': winner['reason_codes']}
    return winner['archetype_id'], selection


def validate_selection(s, domain, selected):
    if not isinstance(s, dict) or set(s) != {'strategy', 'history', 'candidates', 'fit_score', 'recent_use_penalty', 'reason_codes'} or s['strategy'] != SELECTOR_VERSION:
        raise ValueError('invalid selector provenance')
    history = s['history']
    if not isinstance(history, list) or len(history) > HISTORY_LIMIT:
        raise ValueError('invalid selector history')
    ids = []
    for h in history:
        if (not isinstance(h, dict) or set(h) != {'visual_recipe_id', 'archetype_id'}
            or type(h['visual_recipe_id']) is not int or h['visual_recipe_id'] <= 0
            or h['archetype_id'] not in ARCHETYPES):
            raise ValueError('invalid recent selection evidence')
        ids.append(h['visual_recipe_id'])
    if ids != sorted(set(ids), reverse=True):
        raise ValueError('history must be unique newest-first recipe IDs')
    expected = [a.archetype_id for a in ARCHETYPES.values() if a.domain == domain]
    candidates = s['candidates']
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise ValueError('selector needs all three candidates')
    for c, id in zip(candidates, expected):
        if not isinstance(c, dict) or set(c) != {'archetype_id', 'fit_score', 'recent_use_penalty', 'selection_score', 'eligible', 'reason_codes'} or c['archetype_id'] != id:
            raise ValueError('invalid candidate provenance')
        codes = c['reason_codes']
        baseline = id == DEFAULT_ARCHETYPE_BY_DOMAIN[domain]
        if not isinstance(codes, list) or any(not isinstance(x, str) for x in codes) or len(set(codes)) != len(codes):
            raise ValueError('invalid selector reasons')
        if baseline:
            if codes != ['baseline_applicability']:
                raise ValueError('invalid baseline reason')
            fit = 5
        else:
            if any(x not in ARCHETYPES[id].selection_characteristics for x in codes):
                raise ValueError('invalid semantic reason')
            fit = sum(SIGNAL_WEIGHTS[x] for x in codes)
        penalty = min(1.0, sum(h['archetype_id'] == id for h in history) * .25)
        if (type(c['fit_score']) is not int or c['fit_score'] != fit
            or type(c['eligible']) is not bool or c['eligible'] != (baseline or fit >= 6)
            or type(c['recent_use_penalty']) not in (int, float) or c['recent_use_penalty'] != penalty
            or type(c['selection_score']) not in (int, float) or c['selection_score'] != fit - penalty):
            raise ValueError('candidate score does not match evidence')
    if type(s['fit_score']) is not int or type(s['recent_use_penalty']) not in (int, float):
        raise ValueError('invalid selected score types')
    winner = _winner(candidates, domain)
    if winner['archetype_id'] != selected or any(s[k] != winner[k] for k in ('fit_score', 'recent_use_penalty', 'reason_codes')):
        raise ValueError('selected archetype does not match audited ranking')
