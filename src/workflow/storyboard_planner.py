"""Finite deterministic pagination; SQLite owns the handoff to rendering."""
from common.gemini_image import validate_provider_aspect_ratio

SCHEMA_VERSION = 'storyboard_plan_v2'
PLANNER_VERSION = 'balanced_eight_largest_first_v1'
LAYOUTS = {6: (3, 2), 4: (2, 2), 2: (2, 1), 1: (1, 1)}
PROVIDER_ASPECT_RATIOS = {1: '4:5', 2: '3:2', 4: '4:5', 6: '5:4'}
FINAL_WIDTH, FINAL_HEIGHT = 1080, 1350
SLIDE_ASPECT_RATIO = '4:5'
SPLIT_STRATEGY = 'equal_grid_then_fit_4x5_v1'


def validate_board_geometry(board):
    if ((board['cols'], board['rows']) != LAYOUTS.get(board['capacity'])
        or board['provider_aspect_ratio'] != PROVIDER_ASPECT_RATIOS.get(board['capacity'])
        or (board['slide_aspect_ratio'], board['final_width'], board['final_height'])
           != (SLIDE_ASPECT_RATIO, FINAL_WIDTH, FINAL_HEIGHT)
        or board['split_strategy'] not in {SPLIT_STRATEGY, 'english_accepted_v1'}):
        raise ValueError('unsupported storyboard geometry/normalization contract')
    validate_provider_aspect_ratio(board['provider_aspect_ratio'])
    return board


def slide_bounds(domain):
    if domain == 'english':
        return 6, 6
    if domain in {'ai_tech', 'psychology'}:
        return 4, 14
    raise ValueError('unsupported storyboard domain')


def paginate(total, domain):
    low, high = slide_bounds(domain)
    if type(total) is not int or not low <= total <= high:
        raise ValueError(f'storyboard requires {low}-{high} slides; narrow the adaptation')
    remaining, start, boards = total, 1, []
    while remaining:
        # Explicit balanced-eight exception; otherwise minimum boards, largest first.
        capacity = 4 if total == 8 and remaining == 8 else next(c for c in LAYOUTS if c <= remaining)
        cols, rows = LAYOUTS[capacity]
        boards.append(validate_board_geometry(dict(board_index=len(boards) + 1, rows=rows, cols=cols,
            capacity=capacity, slide_start=start, slide_end=start + capacity - 1,
            slide_indices=list(range(start, start + capacity)),
            provider_aspect_ratio=PROVIDER_ASPECT_RATIOS[capacity],
            slide_aspect_ratio=SLIDE_ASPECT_RATIO, final_width=FINAL_WIDTH, final_height=FINAL_HEIGHT,
            split_strategy='english_accepted_v1' if domain == 'english' else SPLIT_STRATEGY)))
        start += capacity
        remaining -= capacity
    return boards


def validate_plan(plan, total, domain):
    if (not isinstance(plan, dict) or set(plan) != {'schema_version', 'planner_version', 'total_slides', 'boards'}
        or plan != make_plan(total, domain)):
        raise ValueError('storyboard plan does not match deterministic pagination')
    return plan


def make_plan(total, domain):
    return dict(schema_version=SCHEMA_VERSION, planner_version=PLANNER_VERSION,
                total_slides=total, boards=paginate(total, domain))


from .workers import local_operation


class StoryboardPlanner:
    def __init__(self, store, *, instance_id='storyboard-planner'):
        self.store, self.instance_id = store, instance_id

    def run_once(self):
        run = self.store.claim('storyboard_plan_runs', 'storyboard_plan_run_id', self.instance_id)
        return None if run is None else self._process(run)

    @local_operation('storyboard_plan_runs', 'storyboard_plan_run_id')
    def _process(self, run):
        return self.store.create_storyboard_plan(run)
