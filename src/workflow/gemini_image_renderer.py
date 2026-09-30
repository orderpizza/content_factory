"""Execute compiled Gemini storyboards, local splitting, and review rendering."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import logging
import os
from time import perf_counter
from random import Random
from statistics import median

from PIL import Image, ImageDraw, ImageFont, ImageOps

from common.gemini_image import GeneratedImage, VertexGeminiImageClient, configured_image_model
from common.failure_disposition import (FailureDisposition, RetryScheduled, classify_failure,
                                        invocation_outcome, provider_status, safe_failure)
from .model_budget import ModelBudgetPolicy
from .workers import local_operation
from .active_review_renderer import ActiveReviewRenderer, _asset

from .active_visual_profiles import PROMPT_COMPILER_VERSION, OVERLAY_PROFILES
from .gemini_prompt_compiler import build_storyboard_prompt, supports_image_rendering

STORYBOARD_COLUMNS = 3
STORYBOARD_ROWS = 2
FOOTER_CTA_PHRASES = (
    "Swipe", "Keep going", "Learn more", "Next tip", "More examples", "Continue", "Next", "See more",
)
OVERLAY_COLOR = (57, 72, 78, 150)
OVERLAY_FONT_SIZE = 32
logger = logging.getLogger(__name__)


class StructuralGridViolation(ValueError):
    """The planner-requested cells cannot be safely extracted."""

    def __init__(self, code: str, evidence: dict):
        super().__init__(code)
        self.code, self.evidence = code, evidence


@dataclass(frozen=True)
class StoryboardSplit:
    slides: list[Image.Image]
    metadata: dict


def _load_planned_board(data: bytes, board: dict) -> Image.Image:
    from .storyboard_planner import validate_board_geometry
    validate_board_geometry(board)
    if len(data) > 40_000_000:
        raise ValueError('storyboard exceeds image byte limit')
    with Image.open(BytesIO(data)) as raw:
        if raw.format not in {'PNG', 'JPEG'} or getattr(raw, 'n_frames', 1) != 1:
            raise ValueError('storyboard must be a single PNG or JPEG')
        width, height = raw.size
        if width * height > 40_000_000:
            raise ValueError('storyboard dimensions unsafe')
        ratio_width, ratio_height = map(int, board['provider_aspect_ratio'].split(':'))
        if (width < board['cols'] * 200 or height < board['rows'] * 250
            or abs((width / height) / (ratio_width / ratio_height) - 1) > .02):
            raise StructuralGridViolation('unextractable_expected_layout', {
                'version': 'expected_grid_v2', 'outcome': 'unextractable_expected_layout',
                'expected_grid': {'columns': board['cols'], 'rows': board['rows']},
                'raw_dimensions': {'width': width, 'height': height}})
        source = ImageOps.exif_transpose(raw).convert('RGB')
        if source.size != raw.size:
            raise ValueError('storyboard orientation inconsistent')
        return source.copy()


def _expected_rectangles(source: Image.Image, board: dict) -> tuple[list, dict]:
    """Search only around planner boundaries; never infer a replacement grid."""
    width, height = source.size
    evidence = {'version': 'expected_grid_v2',
                'expected_grid': {'columns': board['cols'], 'rows': board['rows']},
                'outcome': 'expected_geometry', 'seams': {'vertical': [], 'horizontal': []}}
    if board['capacity'] == 1:
        evidence['outcome'] = 'singleton'
        return [(0, 0, width, height)], evidence
    scale = min(1., 720 / max(width, height))
    preview = source.resize((round(width * scale), round(height * scale)), Image.Resampling.BOX)
    pw, ph = preview.size
    pixels = preview.load()
    background = _border_connected_background(preview)
    bounds = (0, 0, pw, ph)
    if background:
        candidate = _content_bounds(background[0], pw, ph)
        # Trim only small, reliably connected outer margins. Large blank areas
        # inside artwork do not authorize a different board geometry.
        if candidate and all(0 <= delta <= length * .06 for delta, length in
                zip((candidate[0], candidate[1], pw-candidate[2], ph-candidate[3]), (pw, ph, pw, ph))):
            bounds = candidate
    axes = []
    for axis, count, low, high, cross_low, cross_high in (
        ('vertical', board['cols'], bounds[0], bounds[2], bounds[1], bounds[3]),
        ('horizontal', board['rows'], bounds[1], bounds[3], bounds[0], bounds[2])):
        length = high - low
        cuts = []
        for index in range(1, count):
            expected = round(low + length * index / count)
            radius = max(2, round(length / count * .12))
            start, stop = max(low+1, expected-radius), min(high-1, expected+radius+1)
            def pixel(pos, other):
                return pixels[pos, other] if axis == 'vertical' else pixels[other, pos]
            # A seam must span most of the orthogonal board dimension. Lines
            # outside this bounded window never enter the decision.
            scores = {pos: sum(sum(abs(a-b) for a,b in zip(pixel(pos-1,other), pixel(pos,other))) >= 36
                              for other in range(cross_low,cross_high)) / (cross_high-cross_low)
                      for pos in range(start,stop)}
            candidates = [pos for pos, score in scores.items() if score >= .8]
            cut = min(candidates, key=lambda pos: (abs(pos-expected), -scores[pos])) if candidates else expected
            seam = (cut, cut)
            method = 'transition' if candidates else 'expected_geometry'
            if background:
                mask = background[0]
                def ratio(pos):
                    return sum(not mask[other*pw+pos if axis == 'vertical' else pos*pw+other]
                               for other in range(cross_low,cross_high)) / (cross_high-cross_low)
                blanks = [pos for pos in range(start,stop) if ratio(pos) <= .12]
                if blanks:
                    center = min(blanks, key=lambda pos: abs(pos-expected))
                    left, right = center, center+1
                    while left > start and ratio(left-1) <= .16:
                        left -= 1
                    while right < stop and ratio(right) <= .16:
                        right += 1
                    # Bounded runs only: broad flat cell backgrounds are not gutters.
                    if left > start and right < stop and right-left <= length/count*.12:
                        seam, method = (left,right), 'margin'
            cuts.append(seam)
            evidence['seams'][axis].append({'expected': expected, 'start': seam[0], 'end': seam[1],
                                            'method': method, 'search_window': [start, stop]})
        axes.append(list(zip([low]+[cut[1] for cut in cuts], [cut[0] for cut in cuts]+[high])))
    rectangles = [_native_box((x0,y0,x1,y1), preview.size, source.size)
                  for y0,y1 in axes[1] for x0,x1 in axes[0]]
    if any(x1-x0 < 200 or y1-y0 < 250 for x0,y0,x1,y1 in rectangles):
        raise StructuralGridViolation('unextractable_expected_layout', {**evidence, 'outcome': 'cells_too_small'})
    if bounds == (0, 0, pw, ph) and all(item['method'] == 'expected_geometry'
            for axis in evidence['seams'].values() for item in axis):
        rectangles = [(round(c*width/board['cols']), round(r*height/board['rows']),
                       round((c+1)*width/board['cols']), round((r+1)*height/board['rows']))
                      for r in range(board['rows']) for c in range(board['cols'])]
    evidence['preview_dimensions'] = [pw, ph]
    evidence['outer_crop_box'] = list(_native_box(bounds, preview.size, source.size))
    evidence['outcome'] = 'pass' if any(s['method'] != 'expected_geometry'
        for axis in evidence['seams'].values() for s in axis) else 'expected_geometry'
    return rectangles, evidence


def validate_composite_structure(data: bytes, board: dict) -> dict:
    """Validate extraction of exactly the planned cells, not arbitrary artwork lines."""
    source = _load_planned_board(data, board)
    rectangles, evidence = _expected_rectangles(source, board)
    evidence['source_rectangles'] = [list(box) for box in rectangles]
    return evidence


def _load_storyboard(data: bytes) -> tuple[Image.Image, dict]:
    if len(data) > 40_000_000:
        raise ValueError("storyboard exceeds image byte limit")
    with Image.open(BytesIO(data)) as source:
        if source.format not in {"PNG", "JPEG"} or getattr(source, "n_frames", 1) != 1:
            raise ValueError("storyboard must be a single PNG or JPEG")
        width, height = source.size
        if width < 600 or height < 480 or width * height > 40_000_000:
            raise ValueError("storyboard dimensions are unsafe or too small")
        if abs(width / height - 1.25) > 0.04:
            raise ValueError("storyboard does not match 5:4 landscape")
        source = ImageOps.exif_transpose(source).convert("RGB")
        if source.size != (width, height):
            raise ValueError("storyboard orientation is inconsistent")
        return source.copy(), {"width": width, "height": height}


def _equal_grid_rectangles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    return [
        (round(column * width / STORYBOARD_COLUMNS), round(row * height / STORYBOARD_ROWS),
         round((column + 1) * width / STORYBOARD_COLUMNS), round((row + 1) * height / STORYBOARD_ROWS))
        for row in range(STORYBOARD_ROWS) for column in range(STORYBOARD_COLUMNS)
    ]


def _edge_background(preview: Image.Image) -> tuple[tuple[int, int, int], int] | None:
    width, height = preview.size
    pixels = preview.load()
    edge = ([pixels[x, 0] for x in range(width)] + [pixels[x, height - 1] for x in range(width)]
            + [pixels[0, y] for y in range(1, height - 1)]
            + [pixels[width - 1, y] for y in range(1, height - 1)])
    bins = Counter(tuple(channel // 16 for channel in pixel) for pixel in edge)
    key, count = bins.most_common(1)[0]
    if count / len(edge) < 0.60:
        return None
    family = [pixel for pixel in edge if tuple(channel // 16 for channel in pixel) == key]
    color = tuple(round(median([pixel[index] for pixel in family])) for index in range(3))
    distances = sorted(sum(abs(pixel[index] - color[index]) for index in range(3)) for pixel in family)
    return color, min(70, max(18, distances[int(len(distances) * .9)] + 10))


def _border_connected_background(preview: Image.Image) -> tuple[list[bool], tuple[int, int, int], int] | None:
    detected = _edge_background(preview)
    if detected is None:
        return None
    color, tolerance = detected
    width, height = preview.size
    pixels = list(preview.get_flattened_data() if hasattr(preview, "get_flattened_data") else preview.getdata())
    background = [sum(abs(pixel[index] - color[index]) for index in range(3)) <= tolerance
                  for pixel in pixels]
    connected = [False] * len(background)
    queue: deque[int] = deque()
    for x in range(width):
        queue.extend(index for index in (x, (height - 1) * width + x) if background[index] and not connected[index])
    for y in range(1, height - 1):
        queue.extend(index for index in (y * width, y * width + width - 1) if background[index] and not connected[index])
    while queue:
        index = queue.popleft()
        if connected[index]:
            continue
        connected[index] = True
        x, y = index % width, index // width
        for neighbor in (index - 1 if x else None, index + 1 if x + 1 < width else None,
                         index - width if y else None, index + width if y + 1 < height else None):
            if neighbor is not None and background[neighbor] and not connected[neighbor]:
                queue.append(neighbor)
    return connected, color, tolerance


def _content_bounds(mask: list[bool], width: int, height: int) -> tuple[int, int, int, int] | None:
    foreground = [index for index, background in enumerate(mask) if not background]
    if not foreground:
        return None
    xs = [index % width for index in foreground]
    ys = [index // width for index in foreground]
    bounds = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
    if bounds == (0, 0, width, height):
        return None
    return bounds


def _gutter(mask: list[bool], width: int, height: int, bounds: tuple[int, int, int, int], *, axis: str,
            expected: int) -> tuple[int, int] | None:
    left, top, right, bottom = bounds
    if axis == "vertical":
        length, cross = right - left, bottom - top
        ratios = [sum(not mask[y * width + x] for y in range(top, bottom)) / cross for x in range(left, right)]
    else:
        length, cross = bottom - top, right - left
        ratios = [sum(not mask[y * width + x] for x in range(left, right)) / cross for y in range(top, bottom)]
    radius = max(2, length // 7)
    start, stop = max(0, expected - radius), min(length, expected + radius + 1)
    candidate = min(range(start, stop), key=ratios.__getitem__)
    if ratios[candidate] > 0.12:
        return None
    threshold = min(0.16, ratios[candidate] + 0.04)
    run_start = candidate
    while run_start and ratios[run_start - 1] <= threshold:
        run_start -= 1
    run_end = candidate + 1
    while run_end < length and ratios[run_end] <= threshold:
        run_end += 1
    if run_start == 0 or run_end == length:
        return None
    offset = left if axis == "vertical" else top
    return run_start + offset, run_end + offset


def _native_box(box: tuple[int, int, int, int], preview_size: tuple[int, int], source_size: tuple[int, int]) -> tuple[int, int, int, int]:
    preview_width, preview_height = preview_size
    source_width, source_height = source_size
    left, top, right, bottom = box
    return (round(left * source_width / preview_width), round(top * source_height / preview_height),
            round(right * source_width / preview_width), round(bottom * source_height / preview_height))


def _is_background(pixel: tuple[int, int, int], color: tuple[int, int, int], tolerance: int) -> bool:
    return sum(abs(pixel[index] - color[index]) for index in range(3)) <= tolerance


def _native_gutter(source: Image.Image, color: tuple[int, int, int], tolerance: int,
                   bounds: tuple[int, int, int, int], *, axis: str, expected: int) -> tuple[int, int] | None:
    left, top, right, bottom = bounds
    pixels = source.load()
    if axis == "vertical":
        length, cross = right - left, bottom - top
        ratios = [sum(not _is_background(pixels[x, y], color, tolerance) for y in range(top, bottom)) / cross
                  for x in range(left, right)]
        offset = left
    else:
        length, cross = bottom - top, right - left
        ratios = [sum(not _is_background(pixels[x, y], color, tolerance) for x in range(left, right)) / cross
                  for y in range(top, bottom)]
        offset = top
    local_expected = expected - offset
    radius = max(6, length // 16)
    start, stop = max(0, local_expected - radius), min(length, local_expected + radius + 1)
    candidate = min(range(start, stop), key=ratios.__getitem__)
    if ratios[candidate] > 0.12:
        return None
    threshold = min(0.16, ratios[candidate] + 0.04)
    run_start = candidate
    while run_start and ratios[run_start - 1] <= threshold:
        run_start -= 1
    run_end = candidate + 1
    while run_end < length and ratios[run_end] <= threshold:
        run_end += 1
    if run_start == 0 or run_end == length:
        return None
    return run_start + offset, run_end + offset


def _refine_native_bounds(source: Image.Image, color: tuple[int, int, int], tolerance: int,
                          estimate: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    width, height = source.size
    left, top, right, bottom = estimate
    pixels = source.load()
    def first_foreground(start, stop, ratio):
        return next((position for position in range(start, stop) if ratio(position) > .02), None)
    x_ratio = lambda x: sum(not _is_background(pixels[x, y], color, tolerance) for y in range(height)) / height
    y_ratio = lambda y: sum(not _is_background(pixels[x, y], color, tolerance) for x in range(width)) / width
    radius = max(8, round(max(width, height) / 180))
    refined_left = first_foreground(max(0, left - radius), min(width, left + radius + 1), x_ratio)
    refined_top = first_foreground(max(0, top - radius), min(height, top + radius + 1), y_ratio)
    refined_right = next((position for position in range(min(width - 1, right + radius),
                                                          max(-1, right - radius - 1), -1)
                           if x_ratio(position) > .02), None)
    refined_bottom = next((position for position in range(min(height - 1, bottom + radius),
                                                           max(-1, bottom - radius - 1), -1)
                            if y_ratio(position) > .02), None)
    if None in (refined_left, refined_top, refined_right, refined_bottom):
        return estimate
    return refined_left, refined_top, refined_right + 1, refined_bottom + 1


def _adaptive_rectangles(source: Image.Image) -> tuple[list[tuple[int, int, int, int]], dict]:
    width, height = source.size
    scale = min(1.0, 720 / max(width, height))
    preview = source.resize((round(width * scale), round(height * scale)), Image.Resampling.BOX)
    preview_width, preview_height = preview.size
    detected = _border_connected_background(preview)
    if detected is None:
        raise ValueError("no dominant border background family")
    mask, color, tolerance = detected
    bounds = _content_bounds(mask, preview_width, preview_height)
    if bounds is None:
        raise ValueError("outer margins are not confidently detectable")
    left, top, right, bottom = bounds
    first_vertical = _gutter(mask, preview_width, preview_height, bounds, axis="vertical",
                             expected=round((right - left) / 3))
    second_vertical = _gutter(mask, preview_width, preview_height, bounds, axis="vertical",
                              expected=round(2 * (right - left) / 3))
    horizontal = _gutter(mask, preview_width, preview_height, bounds, axis="horizontal",
                         expected=round((bottom - top) / 2))
    if not all((first_vertical, second_vertical, horizontal)):
        raise ValueError("internal gutters are not confidently detectable")
    vertical = (first_vertical, second_vertical)
    columns = ((left, vertical[0][0]), (vertical[0][1], vertical[1][0]), (vertical[1][1], right))
    rows = ((top, horizontal[0]), (horizontal[1], bottom))
    widths = [end - start for start, end in columns]
    heights = [end - start for start, end in rows]
    if min(widths) < 8 or min(heights) < 8 or max(widths) / min(widths) > 1.25 or max(heights) / min(heights) > 1.25:
        raise ValueError("detected panel regions are inconsistent")
    preview_rectangles = [(column[0], row[0], column[1], row[1]) for row in rows for column in columns]
    if any(not .68 <= (right - left) / (bottom - top) <= .95 for left, top, right, bottom in preview_rectangles):
        raise ValueError("detected panel aspect ratios are implausible")
    mapped_bounds = _native_box(bounds, preview.size, source.size)
    native_bounds = _refine_native_bounds(source, color, tolerance, mapped_bounds)
    native_vertical = tuple(
        _native_gutter(source, color, tolerance, native_bounds, axis="vertical",
                       expected=round((start + end) / 2 * width / preview_width))
        for start, end in vertical
    )
    native_horizontal = _native_gutter(source, color, tolerance, native_bounds, axis="horizontal",
                                       expected=round((horizontal[0] + horizontal[1]) / 2 * height / preview_height))
    if not all(native_vertical) or native_horizontal is None:
        raise ValueError("native gutter refinement failed")
    native_columns = ((native_bounds[0], native_vertical[0][0]),
                      (native_vertical[0][1], native_vertical[1][0]),
                      (native_vertical[1][1], native_bounds[2]))
    native_rows = ((native_bounds[1], native_horizontal[0]), (native_horizontal[1], native_bounds[3]))
    rectangles = [(column[0], row[0], column[1], row[1]) for row in native_rows for column in native_columns]
    def gutter_metadata(gutters):
        return [{"start": start, "end": end, "width": end - start} for start, end in gutters]
    return rectangles, {
        "raw_dimensions": {"width": width, "height": height},
        "outer_crop_box": list(native_bounds),
        "gutters": {"vertical": gutter_metadata(native_vertical),
                    "horizontal": gutter_metadata((native_horizontal,))},
        "fallback_used": False,
        "method": "adaptive_border_background_projection_v1",
    }


def split_storyboard_with_metadata(data: bytes) -> StoryboardSplit:
    """Adaptively isolate a 3×2 panel grid, retaining a safe equal-grid fallback."""
    source, raw_dimensions = _load_storyboard(data)
    try:
        rectangles, metadata = _adaptive_rectangles(source)
    except ValueError as error:
        logger.warning("storyboard adaptive split fell back to equal grid: %s", error)
        rectangles = _equal_grid_rectangles(*source.size)
        metadata = {
            "raw_dimensions": raw_dimensions,
            "outer_crop_box": [0, 0, *source.size],
            "gutters": {"vertical": [], "horizontal": []},
            "fallback_used": True,
            "method": "equal_grid_fallback_v1",
        }
    slides = [ImageOps.fit(source.crop(rectangle), (1080, 1350), method=Image.Resampling.LANCZOS,
                           centering=(0.5, 0.5)) for rectangle in rectangles]
    metadata["source_rectangles"] = [list(rectangle) for rectangle in rectangles]
    metadata["normalization"] = dict(method="ImageOps.fit", resampling="LANCZOS", centering=[0.5, 0.5],
                                     slide_aspect_ratio="4:5", final_width=1080, final_height=1350)
    return StoryboardSplit(slides, metadata)


def split_equal_grid(data: bytes, board: dict, *, structural: dict | None = None) -> StoryboardSplit:
    """Extract planner cells using the same bounded seam evidence as validation."""
    from .storyboard_planner import SPLIT_STRATEGY
    source = _load_planned_board(data, board)
    structural = structural or validate_composite_structure(data, board)
    rectangles = structural['source_rectangles']
    slides = [ImageOps.fit(source.crop(box), (board['final_width'], board['final_height']),
                          method=Image.Resampling.LANCZOS, centering=(.5,.5)) for box in rectangles]
    return StoryboardSplit(slides, dict(method=SPLIT_STRATEGY, fallback_used=structural['outcome']=='expected_geometry',
        extraction=structural,
        normalization=dict(method='ImageOps.fit', resampling='LANCZOS', centering=[.5,.5],
                           slide_aspect_ratio=board['slide_aspect_ratio'],
                           final_width=board['final_width'], final_height=board['final_height']),
        raw_dimensions=dict(width=source.width, height=source.height), source_rectangles=rectangles))


def split_storyboard(data: bytes) -> list[Image.Image]:
    """Return six normalized slides; metadata-aware callers use the companion function."""
    return split_storyboard_with_metadata(data).slides


def _overlay_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Use a modern local bold face, with Pillow's font only as a last resort."""
    candidates = (
        os.getenv("CONTENT_FACTORY_FONT_PATH"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
        "DejaVuSans-Bold.ttf",
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=OVERLAY_FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default(size=OVERLAY_FONT_SIZE)


def _draw_arrow(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.line((x - 26, y, x, y), fill=OVERLAY_COLOR, width=3)
    draw.line((x - 9, y - 9, x, y, x - 9, y + 9), fill=OVERLAY_COLOR, width=3)


def footer_cta_phrases(render_id: int, total: int = 6, *, pipeline_id: str = "english") -> list[str | None]:
    """Choose non-repeating, reproducible swipe cues for one render."""
    if type(render_id) is not int or not 4 <= total <= 14 or (pipeline_id == 'english' and total > 6):
        raise ValueError("expression carousel CTA rotation requires six slides")
    rng = Random(f"{OVERLAY_PROFILES[pipeline_id]['cta_namespace']}:{render_id}")
    phrases = rng.sample(FOOTER_CTA_PHRASES, min(total - 1, len(FOOTER_CTA_PHRASES)))
    while len(phrases) < total - 1:
        phrases.append(rng.choice([p for p in FOOTER_CTA_PHRASES if p != phrases[-1]]))
    return [*phrases, None]


def apply_overlays(slide: Image.Image, ordinal: int, total: int, *, cta_phrase: str | None, pipeline_id: str = "english", role: str | None = None) -> Image.Image:
    """Apply a single subdued RGBA type treatment after slide normalization."""
    if slide.size != (1080, 1350) or not 1 <= ordinal <= total or not 4 <= total <= 14 or (pipeline_id == 'english' and total > 6):
        raise ValueError("overlay requires six final-size slides")
    if (ordinal < total) != (cta_phrase is not None):
        raise ValueError("only slides one through five may have a swipe CTA")
    profile = OVERLAY_PROFILES[pipeline_id]
    layer = Image.new("RGBA", slide.size)
    draw = ImageDraw.Draw(layer)
    font = _overlay_font()
    from .content_contract import english_positions
    label = profile['labels'][english_positions(total)[ordinal - 1]] if pipeline_id == 'english' else profile['labels'][ordinal - 1] if role is None and total == 6 else {
        'hook': 'AI / TECH' if pipeline_id == 'ai_tech' else 'PSYCHOLOGY',
        'explanation': 'EXPLAINED', 'example': 'EXAMPLE', 'takeaway': 'TAKEAWAY',
    }[role]
    draw.text((56, 68), label, font=font, fill=OVERLAY_COLOR)
    draw.text((1024, 68), f"{ordinal} / {total}", font=font, fill=OVERLAY_COLOR, anchor="ra")
    if profile["brand"]:
        draw.text((56, 1265), profile["brand"], font=font, fill=OVERLAY_COLOR, anchor="ls")
    if cta_phrase:
        draw.text((970, 1265), cta_phrase, font=font, fill=OVERLAY_COLOR, anchor="rs")
        _draw_arrow(draw, 1024, 1255)
    return Image.alpha_composite(slide.convert("RGBA"), layer).convert("RGB")


class GeminiImageRenderer(ActiveReviewRenderer):
    """Generate persisted boards and assemble one complete ordered review."""
    engine = "gemini_storyboard_designer_v1"

    def __init__(self, store, artifact_root, *, client=None, budget_policy=None):
        super().__init__(store, artifact_root, instance_id="renderer-gemini-image")
        self.budget_policy = budget_policy
        self.client = client

    def _render_assets(self, run, package, spec, recipe, temporary, **kwargs):
        # Domain identity comes from persisted lineage, never an account or model output.
        pipeline_id = self.store.connection.execute(
            "SELECT j.pipeline_id FROM content_packages p "
            "JOIN output_requests o ON o.output_request_id=p.output_request_id "
            "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
            "JOIN content_jobs j ON j.content_job_id=c.content_job_id "
            "WHERE p.content_package_id=?", (run["content_package_id"],),
        ).fetchone()["pipeline_id"]
        return self._render_boards(run, package, spec, recipe, temporary, pipeline_id)

    def _render_boards(self, run, package, spec, recipe, temporary, pipeline_id):
        plan = spec['storyboard_plan']
        if self.client is None:
            self.budget_policy = self.budget_policy or ModelBudgetPolicy.from_environment(configured_image_model(), image=True)
            self.client = VertexGeminiImageClient(max_output_tokens=self.budget_policy.phase_limits['image_rendering'][1])
        if self.budget_policy is not None and self.budget_policy.model_id != self.client.model:
            raise ValueError('image budget policy does not match configured model')
        checkpoint_root = self.artifact_root / f"render-{run['render_run_id']}.checkpoint"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        ctas = footer_cta_phrases(int(run['render_run_id']), plan['total_slides'], pipeline_id=pipeline_id)
        while (board_unit := self.store.next_render_board_unit(run)) is not None:
            board = json.loads(board_unit['board_json'])
            attempt = self.store.begin_render_board_attempt(run, board_unit)
            prompt = build_storyboard_prompt(package, recipe, pipeline_id=pipeline_id, board=board,
                                             reinforce_grid=board_unit['lineage_kind'] == 'structural_retry')
            saved = json.loads(attempt['result_json']) if attempt['result_json'] else None
            if saved:
                invocation = attempt['model_invocation_id']
                from common.gemini import GeminiUsage
                self.client.last_usage = GeminiUsage(**saved['usage']) if saved.get('usage') else None
                provider_latency_ms = saved['provider_latency_ms']
            else:
                invocation = self.store.begin_model_invocation(phase='image_rendering', table='render_runs',
                    key='render_run_id', row=run, request_version='image_storyboard_request_v2',
                    prompt_version=PROMPT_COMPILER_VERSION, schema_version=recipe['renderer_contract_id'],
                    request_value={'prompt_sha256': sha256(prompt.encode()).hexdigest(), 'board': board}, model_id=self.client.model,
                    budget_policy=self.budget_policy, render_board_attempt_id=attempt['render_board_attempt_id'])
                from common.gemini_image import configured_image_size
                self.store.record_model_request(invocation, prompt, None, {
                    'aspect_ratio': board['provider_aspect_ratio'], 'image_size': configured_image_size(),
                    'response_modalities': ['TEXT', 'IMAGE'], 'candidate_count': 1,
                    'max_output_tokens': getattr(self.client, 'max_output_tokens', None)})
                started = perf_counter()
                try:
                    generated = self.client.generate_image(prompt, aspect_ratio=board['provider_aspect_ratio'])
                except Exception as error:
                    disposition = classify_failure(error)
                    # This boundary is immediately around the provider call.  An
                    # untyped exception here could follow a sent request, so do
                    # not relabel it as a safe local failure or replay it.
                    if disposition is FailureDisposition.LOCAL:
                        disposition = FailureDisposition.AMBIGUOUS_EXTERNAL
                    diagnostic = safe_failure(stage='image_rendering', disposition=disposition,
                        code=(f'http_{provider_status(error)}' if provider_status(error) is not None else type(error).__name__.casefold()),
                        attempt=int(attempt['attempt_number']), retryable=disposition is FailureDisposition.PROVIDER_TRANSIENT,
                        slides=board['slide_indices'], board_capacity=board['capacity'])
                    outcome = ('ambiguous_outcome' if disposition is FailureDisposition.AMBIGUOUS_EXTERNAL
                               else invocation_outcome(error))
                    self.store.finish_model_invocation(invocation, outcome=outcome, usage=self.client.last_usage,
                        error=json.dumps(diagnostic, sort_keys=True), budget_policy=self.budget_policy, provider_error=error)
                    if disposition is FailureDisposition.PROVIDER_TRANSIENT:
                        self.store.schedule_render_provider_retry(run, attempt, diagnostic)
                        continue
                    self.store.finish_render_board_attempt(
                        attempt, run=run, status=('provider_terminal' if disposition is FailureDisposition.PROVIDER_TERMINAL else
                                         'ambiguous' if disposition is FailureDisposition.AMBIGUOUS_EXTERNAL else 'local_failed'),
                        diagnostic=diagnostic, board_status='ambiguous' if disposition is FailureDisposition.AMBIGUOUS_EXTERNAL else 'failed')
                    continue
                self.store.reconcile_model_usage(invocation, self.client.last_usage, self.budget_policy)
                provider_latency_ms = round((perf_counter() - started) * 1000)
            try:
                if saved:
                    raw_data = Path(saved['raw']['checkpoint_path']).read_bytes()
                    if sha256(raw_data).hexdigest() != saved['raw']['sha256']:
                        raise ValueError('persisted raw board hash changed')
                    generated = GeneratedImage(raw_data, saved['raw']['mime_type'])
                if not isinstance(generated, GeneratedImage):
                    raise ValueError('image client did not preserve media metadata')
                suffix = '' if board_unit['lineage_kind'] == 'planned' and attempt['attempt_number'] == 1 else f"-request-{attempt['render_board_attempt_id']}"
                raw_name = f"raw-storyboard-{board['board_index']:02d}{suffix}{generated.extension}"
                raw = checkpoint_root / raw_name
                if not saved:
                    raw.write_bytes(generated.data)
                    with raw.open('rb') as handle:
                        os.fsync(handle.fileno())
                usage = self.client.last_usage
                output = dict(stage='generated', provider_latency_ms=provider_latency_ms,
                    usage=None if usage is None else dict(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                                         total_tokens=usage.total_tokens, model=usage.model),
                    raw=dict(checkpoint_path=str(raw), sha256=sha256(generated.data).hexdigest(), mime_type=generated.mime_type))
                self.store.checkpoint_render_board_output(run, attempt, output)
                structural = validate_composite_structure(generated.data, board)
                output.update(stage='validated', structural=structural)
                self.store.checkpoint_render_board_output(run, attempt, output)
                split = (split_storyboard_with_metadata(generated.data)
                         if board['split_strategy'] == 'english_accepted_v1'
                         else split_equal_grid(generated.data, board, structural=structural))
                output.update(stage='extracted', split=split.metadata)
                self.store.checkpoint_render_board_output(run, attempt, output)
                checkpoints = []
                for cell, (ordinal, slide) in enumerate(zip(board['slide_indices'], split.slides)):
                    path = checkpoint_root / f'unit-{ordinal:02d}.png'
                    apply_overlays(slide, ordinal, plan['total_slides'], cta_phrase=ctas[ordinal-1],
                        pipeline_id=pipeline_id, role=package['visual_units'][ordinal-1]['role']).save(path, format='PNG')
                    asset = _asset(path, 'preview_png', ordinal, 1080, 1350)
                    checkpoints.append(dict(ordinal=ordinal, checkpoint_path=str(path), sha256=asset['sha256'], bytes=asset['bytes'],
                        source_cell=dict(row=cell // board['cols'] + 1, column=cell % board['cols'] + 1),
                        source_rectangle=split.metadata['source_rectangles'][cell], footer_cta=ctas[ordinal-1], board_index=board['board_index']))
                result = dict(**board, provider_latency_ms=provider_latency_ms, model_invocation_id=invocation,
                    prompt_sha256=sha256(prompt.encode()).hexdigest(), raw=dict(checkpoint_path=str(raw), filename=raw.name,
                    mime_type=generated.mime_type, extension=generated.extension, bytes=len(generated.data),
                    sha256=sha256(generated.data).hexdigest()), split=split.metadata, structural=structural)
                self.store.complete_render_board_units(run, attempt, checkpoints, result)
                self.store.finish_model_invocation(invocation, outcome='succeeded', usage=self.client.last_usage,
                    response_value={'sha256': sha256(generated.data).hexdigest()}, budget_policy=self.budget_policy)
            except StructuralGridViolation as error:
                diagnostic = safe_failure(stage='image_rendering', disposition=FailureDisposition.OUTPUT_CONTRACT,
                    code=error.code, attempt=int(attempt['attempt_number']), slides=board['slide_indices'],
                    requested_grid=f"{board['cols']}x{board['rows']}", extraction_outcome=error.evidence.get('outcome'),
                    action='retry_then_reduce_batch')
                self.store.finish_model_invocation(invocation, outcome='structural_failed', usage=self.client.last_usage,
                    response_value={'sha256': sha256(generated.data).hexdigest()}, error=json.dumps(diagnostic, sort_keys=True),
                    budget_policy=self.budget_policy, resume_image_output=bool(saved))
                if board_unit['lineage_kind'] != 'structural_retry':
                    self.store.split_render_board_unit(run, attempt, [board], diagnostic,
                        structural_evidence=error.evidence, lineage_kind='structural_retry')
                    continue
                if board['capacity'] > 1:
                    from .storyboard_planner import split_for_structural_fallback
                    self.store.split_render_board_unit(run, attempt,
                        split_for_structural_fallback(board, package['visual_units'], pipeline_id), diagnostic,
                        structural_evidence=error.evidence)
                    continue
                self.store.finish_render_board_attempt(attempt, run=run, status='structural_failed', structural_evidence=error.evidence,
                                                       diagnostic=diagnostic, board_status='failed')
                continue
            except Exception:
                self.store.finish_model_invocation(invocation, outcome='invalid_output', usage=self.client.last_usage,
                    error='local image processing failure', budget_policy=self.budget_policy)
                self.store.finish_render_board_attempt(attempt, run=run, status='invalid_output',
                    diagnostic=safe_failure(stage='image_rendering', disposition=FailureDisposition.LOCAL,
                        code='local_image_processing_failure', attempt=int(attempt['attempt_number']), slides=board['slide_indices']),
                    board_status='failed')
                continue

        if self.store.finish_incomplete_render(run):
            raise RetryScheduled()

        from .model_trace import invocation_cost, aggregate_cost
        assets, provenance, boards = [], [], []
        for result in self.store.render_successful_board_results(run):
            source = Path(result['raw']['checkpoint_path'])
            target = temporary / result['raw']['filename']
            target.write_bytes(source.read_bytes())
            result['raw'].pop('checkpoint_path', None)
            result['cost'] = invocation_cost(self.store.connection, result['model_invocation_id'])
            result.pop('render_board_attempt_id', None)
            result.pop('render_board_unit_id', None)
            boards.append(result)
        for checkpoint in self.store.render_unit_checkpoints(run):
            path = temporary / f"unit-{checkpoint['ordinal']:02d}.png"
            path.write_bytes(Path(checkpoint['checkpoint_path']).read_bytes())
            asset = _asset(path, 'preview_png', checkpoint['ordinal'], 1080, 1350)
            if asset['sha256'] != checkpoint['sha256']:
                raise ValueError('persisted render checkpoint hash changed')
            assets.append(asset)
            provenance.append(dict(ordinal=checkpoint['ordinal'], board_index=checkpoint['board_index'],
                model_invocation_id=checkpoint['model_invocation_id'],
                render_board_attempt_id=checkpoint['render_board_attempt_id'], source_cell=checkpoint['source_cell'],
                source_rectangle=checkpoint['source_rectangle'], footer_cta=checkpoint['footer_cta'],
                final=dict(filename=path.name, sha256=asset['sha256'])))
        all_costs = [invocation_cost(self.store.connection, row[0]) for row in self.store.connection.execute(
            "SELECT model_invocation_id FROM model_invocations WHERE phase='image_rendering' AND entity_type='render_run' "
            "AND entity_id=? AND outcome!='blocked' ORDER BY model_invocation_id", (run['render_run_id'],))]
        return assets, dict(cost=aggregate_cost(all_costs), model_id=self.client.model, prompt_version=PROMPT_COMPILER_VERSION,
            pipeline_id=pipeline_id, archetype_id=recipe['archetype_id'], archetype_version=recipe['archetype_version'],
            account_visual_profile_id=recipe['account_visual_profile_id'], prompt_compiler_version=recipe['prompt_compiler_version'],
            renderer_contract_id=recipe['renderer_contract_id'], overlay_profile_id=recipe['overlay_profile_id'],
            selection=recipe['selection'], boards=boards, slides=provenance,
            overlay_version=OVERLAY_PROFILES[pipeline_id]['overlay_version'],
            overlay=dict(background='transparent', brand_text=OVERLAY_PROFILES[pipeline_id]['brand'],
                         labels=list(OVERLAY_PROFILES[pipeline_id]['labels']),
                         cta_namespace=OVERLAY_PROFILES[pipeline_id]['cta_namespace'], footer_cta_phrases=ctas))


class DispatchVisualRenderer(ActiveReviewRenderer):
    """Dispatch eligible account archetypes to one Gemini renderer, with no fallback."""
    def __init__(self, store, artifact_root, *, image_client=None, budget_policy=None):
        super().__init__(store, artifact_root, instance_id="renderer-gemini-review")
        self.image_renderer = GeminiImageRenderer(store, artifact_root, client=image_client,
                                                  budget_policy=budget_policy)

    @local_operation("render_runs", "render_run_id")
    def _process(self, run):
        row = self.store.connection.execute(
            "SELECT p.package_json,v.recipe_json,j.pipeline_id FROM content_packages p "
            "JOIN visual_recipes v ON v.visual_recipe_id=? "
            "JOIN output_requests o ON o.output_request_id=p.output_request_id "
            "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
            "JOIN content_jobs j ON j.content_job_id=c.content_job_id "
            "WHERE p.content_package_id=?",
            (run["visual_recipe_id"], run["content_package_id"]),
        ).fetchone()
        if row is None:
            raise ValueError("render run references a missing package")
        if not supports_image_rendering(json.loads(row["package_json"]), json.loads(row["recipe_json"]),
                                        pipeline_id=row["pipeline_id"]):
            domain = "English" if row["pipeline_id"] == "english" else row["pipeline_id"]
            self.store.block_render(run, f"Gemini visual renderer not implemented for this {domain} format.")
            return None
        return self.image_renderer._process(run)
