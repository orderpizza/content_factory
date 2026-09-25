"""Small typed human constraint grammar; replay ordered messages, never summaries.

Latest explicit value wins for scalar fields. `only` replaces included domains;
include/exclude operations update the sets and remove the opposite membership.
Unknown prose remains available to Intake; it cannot invent typed constraints.
"""
import re

VERSION = 'human_constraints_v1'
NUMBERS = dict(zip(('one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen'), range(1,15)))
DOMAIN_NAMES = {'english': 'english', 'ai/tech': 'ai_tech', 'ai tech': 'ai_tech', 'ai_tech': 'ai_tech', 'psychology': 'psychology'}
DOMAIN = r'(english|ai/tech|ai tech|ai_tech|psychology)'
COUNT = re.compile(r'\b(' + '|'.join(NUMBERS) + r'|[0-9]+)[ -]+slides?\b', re.I)
TYPED_KEYS = {'content_slide_count', 'included_domains', 'excluded_domains', 'platform', 'output_format', 'language'}


def extract_constraints(messages):
    values, provenance = {}, []
    included, excluded = [], []
    for message in messages:
        if message.get('author_kind') != 'human':
            continue
        text = message['body']
        events = []
        for match in COUNT.finditer(text):
            raw = match[1].lower()
            events.append((match.start(), 'content_slide_count', int(raw) if raw.isdigit() else NUMBERS[raw], match.group()))
        domain_list = DOMAIN + r'(?:\s*(?:,|and|&)\s*' + DOMAIN + r')*'
        domain_patterns = [
            (r'\b('+domain_list+r')\s+only\b|\bonly\s+('+domain_list+r')\b', 'only'),
            (r"\b(?:do not discuss|don't discuss|exclude|excluding|without|no)\s+("+domain_list+r')\b', 'exclude'),
            (r'\b(?:include|including|also cover)\s+('+domain_list+r')\b', 'include'),
        ]
        for pattern, kind in domain_patterns:
            for match in re.finditer(pattern, text, re.I):
                domains = [DOMAIN_NAMES[m.group().lower()] for m in re.finditer(DOMAIN, match.group(), re.I)]
                for index, domain in enumerate(domains):
                    events.append((match.start()+index, kind if index == 0 or kind != 'only' else 'include', domain, match.group()))
        patterns = [
            (r'\b(?:on|for)\s+(instagram)\b', 'platform'),
            (r'\b(carousel)\b', 'output_format'),
            (r'\b(?:in English|English language|English only)\b', 'language'),
        ]
        for pattern, kind in patterns:
            for match in re.finditer(pattern, text, re.I):
                raw = next((g for g in match.groups() if g), 'english').lower()
                events.append((match.start(), kind, DOMAIN_NAMES.get(raw, raw), match.group()))
        for _, kind, value, wording in sorted(events):
            if kind in {'only', 'include', 'exclude'}:
                if kind == 'only':
                    included = [value]
                elif kind == 'include' and value not in included:
                    included.append(value)
                if kind == 'exclude':
                    included = [d for d in included if d != value]
                    if value not in excluded: excluded.append(value)
                else:
                    excluded = [d for d in excluded if d != value]
            else:
                values[kind] = value
            provenance.append({'message_id': message.get('message_id'), 'wording': wording, 'operation': kind, 'value': value})
    if included: values['included_domains'] = sorted(included)
    if excluded: values['excluded_domains'] = sorted(excluded)
    return values, provenance


def editorial_scope(brief):
    """Explicit scope wins; a named learning subject is not behavioral evidence."""
    constraints = brief.get('constraints', {})
    included = set(constraints.get('included_domains', []))
    excluded = set(constraints.get('excluded_domains', []))
    if not included:
        included = set(brief.get('requested_subject_domains', []))
    if not included:
        topic = brief.get('topic', '')
        if re.search(r'\bEnglish\s+(?:expression|idiom|phrase|vocabulary|word|grammar)\b', topic, re.I):
            included = {'english'}
    return included, excluded
