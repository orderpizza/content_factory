"""Text-aware contiguous render pagination; content pagination is already frozen."""
from copy import deepcopy
from common.gemini_image import validate_provider_aspect_ratio
from .render_text_policy import (MEASUREMENT_VERSION, POLICY_VERSION,
                               PROVISIONAL_CAPACITY_BUDGETS, measure_slide, assess_board)

SCHEMA_VERSION = 'storyboard_plan_v3'
PLANNER_VERSION = 'text_load_contiguous_v1'
LAYOUTS = {6: (3, 2), 4: (2, 2), 2: (2, 1), 1: (1, 1)}
PROVIDER_ASPECT_RATIOS = {1: '4:5', 2: '3:2', 4: '4:5', 6: '5:4'}
FINAL_WIDTH, FINAL_HEIGHT = 1080, 1350
SLIDE_ASPECT_RATIO = '4:5'
SPLIT_STRATEGY = 'equal_grid_then_fit_4x5_v1'
CALIBRATION_MODE = 'forced_fidelity_experiment_v1'


def validate_board_geometry(board):
    if ((board['cols'], board['rows']) != LAYOUTS.get(board['capacity'])
        or board['provider_aspect_ratio'] != PROVIDER_ASPECT_RATIOS.get(board['capacity'])
        or (board['slide_aspect_ratio'], board['final_width'], board['final_height'])
           != (SLIDE_ASPECT_RATIO, FINAL_WIDTH, FINAL_HEIGHT)
        or board['split_strategy'] not in {SPLIT_STRATEGY, 'english_accepted_v1'}
        or (board['split_strategy'] == 'english_accepted_v1' and board['capacity'] != 6)):
        raise ValueError('unsupported storyboard geometry/normalization contract')
    validate_provider_aspect_ratio(board['provider_aspect_ratio'])
    return board


def slide_bounds(domain):
    if domain == 'english':
        return 6, 6
    if domain in {'ai_tech', 'psychology'}:
        return 4, 14
    raise ValueError('unsupported storyboard domain')


def _board(slides, domain, start, capacity, index, mode):
    selected = slides[start:start + capacity]
    aggregate, violations, density = assess_board(selected, capacity)
    cols, rows = LAYOUTS[capacity]
    return validate_board_geometry(dict(board_index=index, rows=rows, cols=cols, capacity=capacity,
        slide_start=start + 1, slide_end=start + capacity, slide_indices=list(range(start + 1, start + capacity + 1)),
        provider_aspect_ratio=PROVIDER_ASPECT_RATIOS[capacity], slide_aspect_ratio=SLIDE_ASPECT_RATIO,
        final_width=FINAL_WIDTH, final_height=FINAL_HEIGHT,
        split_strategy='english_accepted_v1' if domain == 'english' and capacity == 6 else SPLIT_STRATEGY,
        measurement_version=MEASUREMENT_VERSION, text_policy_version=POLICY_VERSION,
        render_text_budget=deepcopy(PROVISIONAL_CAPACITY_BUDGETS[capacity]),
        slide_text_load=selected, text_load=aggregate, budget_violations=violations,
        density=dict(numerator=density.numerator, denominator=density.denominator), planning_mode=mode))


def paginate(units, domain, *, calibration_capacities=None):
    low, high = slide_bounds(domain)
    if not isinstance(units, list) or not low <= len(units) <= high:
        raise ValueError(f'storyboard requires {low}-{high} final visual units')
    slides = [measure_slide(u) for u in units]
    total = len(slides)
    if calibration_capacities is not None:
        capacities = tuple(calibration_capacities)
        if (not capacities or any(type(c) is not int or c not in LAYOUTS for c in capacities)
            or sum(capacities) != total):
            raise ValueError('calibration capacities must exactly partition the package')
        mode = CALIBRATION_MODE
    else:
        # Exhaust all contiguous partitions (at most 14 slides). Keep the full
        # partition objective: greedy suffix headroom can give a wrong global tie.
        candidates = {}
        for start in range(total):
            for capacity in LAYOUTS:
                if start + capacity <= total:
                    _, violations, density = assess_board(slides[start:start + capacity], capacity)
                    if not violations:
                        candidates[start, capacity] = density
        def partitions(start):
            if start == total:
                yield (), ()
            for capacity in LAYOUTS:
                if (start, capacity) in candidates:
                    for tail, densities in partitions(start + capacity):
                        yield (capacity, *tail), (candidates[start, capacity], *densities)
        options = list(partitions(0))
        if not options:
            raise ValueError('render text budget exceeded even for single slides; revise adaptation without dropping meaning')
        capacities, _ = min(options, key=lambda p: (len(p[0]), max(p[1]), tuple(-c for c in p[0])))
        mode = 'automatic'
    boards, start = [], 0
    for index, capacity in enumerate(capacities, 1):
        boards.append(_board(slides, domain, start, capacity, index, mode))
        start += capacity
    return boards


def make_plan(units, domain, *, calibration_capacities=None):
    boards = paginate(units, domain, calibration_capacities=calibration_capacities)
    return dict(schema_version=SCHEMA_VERSION, planner_version=PLANNER_VERSION,
                total_slides=len(units), boards=boards)


def validate_plan(plan, units, domain):
    forced = None
    if isinstance(plan, dict) and plan.get('boards') and plan['boards'][0].get('planning_mode') == CALIBRATION_MODE:
        forced = [b['capacity'] for b in plan['boards']]
    if plan != make_plan(units, domain, calibration_capacities=forced):
        raise ValueError('storyboard plan does not match deterministic text pagination')
    return plan


def validate_board(board, units, domain):
    """Compiler validates this exact slice; the renderer validates the whole plan."""
    try:
        start, capacity, index = board['slide_start'] - 1, board['capacity'], board['board_index']
        if (type(start) is not int or start < 0 or type(capacity) is not int or capacity not in LAYOUTS
            or start + capacity > len(units) or type(index) is not int or index < 1
            or board['planning_mode'] not in {'automatic', CALIBRATION_MODE}):
            raise ValueError('invalid board range/mode')
        expected = _board([measure_slide(u) for u in units], domain, start, capacity, index, board['planning_mode'])
        if board != expected or (board['budget_violations'] and board['planning_mode'] == 'automatic'):
            raise ValueError('board does not match deterministic text plan')
    except (KeyError, TypeError) as error:
        raise ValueError('invalid board contract') from error
    return board


from .workers import local_operation


class StoryboardPlanner:
    def __init__(self, store, *, instance_id='storyboard-planner', calibration_capacities=None):
        self.store, self.instance_id = store, instance_id
        # Only the explicitly opt-in acceptance runner supplies forced strategies.
        self.calibration_capacities = calibration_capacities

    def run_once(self):
        run = self.store.claim('storyboard_plan_runs', 'storyboard_plan_run_id', self.instance_id)
        return None if run is None else self._process(run)

    @local_operation('storyboard_plan_runs', 'storyboard_plan_run_id')
    def _process(self, run):
        return self.store.create_storyboard_plan(run, calibration_capacities=self.calibration_capacities)
