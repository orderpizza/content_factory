"""Local render-load measurement; these are provisional calibration budgets, not model limits."""
from fractions import Fraction

MEASUREMENT_VERSION = 'rendered_text_load_v2'
POLICY_VERSION = 'render_text_calibration_v2'

# Input copy is already final. Count Unicode code points (including whitespace),
# whitespace-delimited words, and nonempty logical lines, without rewriting it.
# A region is a nonempty title or body, not an inferred pixel/line-wrap region.
# Local header/footer overlays are not rendered by Gemini and are excluded.
def measure_slide(unit):
    title, body = unit['title'], unit['body']
    title_lines = [line for line in title.splitlines() if line.strip()]
    body_lines = [line for line in body.splitlines() if line.strip()]
    lines = title_lines + body_lines
    return dict(title_characters=len(title), title_words=len(title.split()),
                body_characters=len(body), body_words=len(body.split()),
                title_non_empty_lines=len(title_lines), body_non_empty_lines=len(body_lines),
                total_words=len(title.split()) + len(body.split()),
                total_characters=len(title) + len(body), total_lines=len(lines),
                total_text_regions=int(bool(title.strip())) + int(bool(body.strip())),
                longest_line_characters=max(map(len, lines), default=0),
                longest_line_words=max((len(line.split()) for line in lines), default=0))


def measure_board(slides):
    aggregate_keys = ('title_characters', 'title_words', 'body_characters', 'body_words',
                      'title_non_empty_lines', 'body_non_empty_lines', 'total_characters',
                      'total_words', 'total_lines', 'total_text_regions')
    result = dict(slide_count=len(slides), **{key: sum(s[key] for s in slides) for key in aggregate_keys})
    result['total_rendered_text_regions'] = result['total_text_regions']
    for name in ('characters', 'words', 'lines'):
        result[f'maximum_slide_{name}'] = max((s[f'total_{name}'] for s in slides), default=0)
    for key in ('title_characters', 'title_words', 'body_characters', 'body_words',
                'title_non_empty_lines', 'body_non_empty_lines', 'longest_line_characters',
                'longest_line_words', 'total_text_regions'):
        result[f'maximum_slide_{key}'] = max((s[key] for s in slides), default=0)
    result['longest_line_characters'] = max((s['longest_line_characters'] for s in slides), default=0)
    result['longest_line_words'] = max((s['longest_line_words'] for s in slides), default=0)
    return result


def _budget(words, characters, lines, slide_words, slide_characters, slide_lines, capacity,
            *, title_words=12, title_characters=96, title_lines=2, longest_words=22,
            longest_characters=180):
    return dict(
        board=dict(total_words=words, total_characters=characters, total_lines=lines,
                   total_text_regions=capacity * 2, longest_line_words=longest_words,
                   longest_line_characters=longest_characters),
        slide=dict(total_words=slide_words, total_characters=slide_characters,
                   total_lines=slide_lines, total_text_regions=2, title_words=title_words,
                   title_characters=title_characters, title_non_empty_lines=title_lines,
                   longest_line_words=longest_words, longest_line_characters=longest_characters),
    )


# Smaller boards preserve legitimate English dialogue/qualification copy. A long
# slide may require a singleton; an unrenderable slide fails, never loses words.
PROVISIONAL_CAPACITY_BUDGETS = {
    # These are fidelity calibration limits, deliberately lower than content
    # readability ceilings.  They never truncate or rewrite copy.
    1: _budget(80, 720, 7, 80, 720, 7, 1, longest_words=80, longest_characters=720),
    2: _budget(110, 1000, 14, 80, 720, 7, 2, longest_words=80, longest_characters=720),
    4: _budget(100, 720, 22, 40, 360, 6, 4, longest_words=50, longest_characters=360),
    6: _budget(110, 800, 26, 35, 240, 5, 6, longest_words=40, longest_characters=240),
}


def assess_board(slides, capacity):
    budget = PROVISIONAL_CAPACITY_BUDGETS[capacity]
    aggregate = measure_board(slides)
    violations = [f'slide:{i}:{key}' for i, slide in enumerate(slides, 1)
                  for key, maximum in budget['slide'].items() if slide[key] > maximum]
    violations += [f'board:{key}' for key, maximum in budget['board'].items() if aggregate[key] > maximum]
    # Regions are fixed at two per slide and cannot distinguish headroom. Lines
    # are hard constraints; density compares copy volume, without floating ties.
    density = max([Fraction(aggregate[key], budget['board'][key])
                   for key in ('total_words', 'total_characters', 'longest_line_words', 'longest_line_characters')] +
                  [Fraction(s[key], budget['slide'][key]) for s in slides
                   for key in ('total_words', 'total_characters', 'title_words', 'title_characters',
                               'longest_line_words', 'longest_line_characters')])
    return aggregate, violations, density
