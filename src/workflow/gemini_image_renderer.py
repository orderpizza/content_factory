"""Execute compiled Gemini storyboards, local splitting, and review rendering."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from random import Random
from statistics import median

from PIL import Image, ImageDraw, ImageFont, ImageOps

from common.gemini_image import GeneratedImage, VertexGeminiImageClient, configured_image_model
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


@dataclass(frozen=True)
class StoryboardSplit:
    slides: list[Image.Image]
    metadata: dict


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


def split_equal_grid(data, board):
    """Strict persisted-grid crop; no margin inference or content-dependent cropping."""
    from .storyboard_planner import validate_board_geometry, SPLIT_STRATEGY
    validate_board_geometry(board)
    cols, rows = board['cols'], board['rows']
    if board['split_strategy'] != SPLIT_STRATEGY:
        raise ValueError('equal-grid splitter requires its planned normalization strategy')
    if len(data) > 40_000_000:
        raise ValueError('storyboard exceeds image byte limit')
    with Image.open(BytesIO(data)) as raw:
        if raw.format not in {'PNG', 'JPEG'} or getattr(raw, 'n_frames', 1) != 1:
            raise ValueError('storyboard must be one PNG/JPEG')
        width, height = raw.size
        if width * height > 40_000_000 or width < cols * 200 or height < rows * 250:
            raise ValueError('storyboard dimensions unsafe or too small')
        if width % cols or height % rows:
            raise ValueError('storyboard dimensions are not divisible by the planned grid')
        ar_width, ar_height = map(int, board['provider_aspect_ratio'].split(':'))
        # Permit provider pixel rounding, but not a different board shape (2% relative).
        if abs((width / height) / (ar_width / ar_height) - 1) > 0.02:
            raise ValueError('storyboard aspect ratio does not match the requested provider ratio')
        source = ImageOps.exif_transpose(raw).convert('RGB')
        if source.size != (width, height):
            raise ValueError('storyboard orientation inconsistent')
        cw, ch = width // cols, height // rows
        rectangles = [(c*cw, r*ch, (c+1)*cw, (r+1)*ch) for r in range(rows) for c in range(cols)]
        if len(rectangles) != board['capacity']:
            raise ValueError('split cell count does not match the storyboard plan')
        slides = [ImageOps.fit(source.crop(box), (board['final_width'], board['final_height']),
                              method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)) for box in rectangles]
    return StoryboardSplit(slides, dict(method=SPLIT_STRATEGY, fallback_used=False,
        normalization=dict(method='ImageOps.fit', resampling='LANCZOS', centering=[0.5, 0.5],
                           slide_aspect_ratio=board['slide_aspect_ratio'],
                           final_width=board['final_width'], final_height=board['final_height']),
        raw_dimensions=dict(width=width, height=height), source_rectangles=[list(b) for b in rectangles]))


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
    if type(render_id) is not int or not 4 <= total <= 14 or (pipeline_id == 'english' and total != 6):
        raise ValueError("expression carousel CTA rotation requires six slides")
    rng = Random(f"{OVERLAY_PROFILES[pipeline_id]['cta_namespace']}:{render_id}")
    phrases = rng.sample(FOOTER_CTA_PHRASES, min(total - 1, len(FOOTER_CTA_PHRASES)))
    while len(phrases) < total - 1:
        phrases.append(rng.choice([p for p in FOOTER_CTA_PHRASES if p != phrases[-1]]))
    return [*phrases, None]


def apply_overlays(slide: Image.Image, ordinal: int, total: int, *, cta_phrase: str | None, pipeline_id: str = "english", role: str | None = None) -> Image.Image:
    """Apply a single subdued RGBA type treatment after slide normalization."""
    if slide.size != (1080, 1350) or not 1 <= ordinal <= total or not 4 <= total <= 14 or (pipeline_id == 'english' and total != 6):
        raise ValueError("overlay requires six final-size slides")
    if (ordinal < total) != (cta_phrase is not None):
        raise ValueError("only slides one through five may have a swipe CTA")
    profile = OVERLAY_PROFILES[pipeline_id]
    layer = Image.new("RGBA", slide.size)
    draw = ImageDraw.Draw(layer)
    font = _overlay_font()
    label = profile['labels'][ordinal - 1] if pipeline_id == 'english' or role is None and total == 6 else {
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
    """Generate and split one active-domain Gemini storyboard."""
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
        if pipeline_id != 'english':
            return self._render_boards(run, package, spec, recipe, temporary, pipeline_id)
        prompt = build_storyboard_prompt(package, recipe, pipeline_id=pipeline_id)
        profile = OVERLAY_PROFILES[pipeline_id]
        if self.client is None:
            self.budget_policy = self.budget_policy or ModelBudgetPolicy.from_environment(
                configured_image_model(), image=True,
            )
            self.client = VertexGeminiImageClient(
                max_output_tokens=self.budget_policy.phase_limits["image_rendering"][1],
            )
        if self.budget_policy is not None and self.budget_policy.model_id != self.client.model:
            raise ValueError("image budget policy does not match the configured model")
        invocation = self.store.begin_model_invocation(
            phase="image_rendering", table="render_runs", key="render_run_id", row=run,
            request_version="image_storyboard_request_v1", prompt_version=PROMPT_COMPILER_VERSION,
            schema_version="image_storyboard_3x2_v1", request_value={"prompt": prompt},
            model_id=self.client.model, budget_policy=self.budget_policy,
        )
        try:
            generated = self.client.generate_image(prompt)
        except Exception:
            self.store.finish_model_invocation(
                invocation, outcome="transport_failed", usage=self.client.last_usage,
                error="storyboard generation failed", budget_policy=self.budget_policy,
            )
            raise
        try:
            if not isinstance(generated, GeneratedImage):
                raise ValueError("image client did not preserve storyboard media metadata")
            data = generated.data
            split = split_storyboard_with_metadata(data)
            slides = split.slides
            raw = temporary / f"raw-storyboard{generated.extension}"
            raw.write_bytes(data)
            assets, provenance = [], []
            cta_phrases = footer_cta_phrases(int(run["render_run_id"]), len(slides), pipeline_id=pipeline_id)
            for ordinal, slide in enumerate(slides, 1):
                path = temporary / f"unit-{ordinal:02d}.png"
                apply_overlays(slide, ordinal, len(slides), cta_phrase=cta_phrases[ordinal - 1], pipeline_id=pipeline_id).save(
                    path, format="PNG", optimize=False,
                )
                asset = _asset(path, "preview_png", ordinal, 1080, 1350)
                assets.append(asset)
                provenance.append({
                    "ordinal": ordinal, "board_index": 1, "model_invocation_id": invocation,
                    "source_cell": {"row": (ordinal - 1) // STORYBOARD_COLUMNS + 1,
                                    "column": (ordinal - 1) % STORYBOARD_COLUMNS + 1},
                    "source_rectangle": split.metadata["source_rectangles"][ordinal - 1],
                    "footer_cta": cta_phrases[ordinal - 1],
                    "final": {"filename": path.name, "sha256": asset["sha256"]},
                })
        except Exception:
            self.store.finish_model_invocation(
                invocation, outcome="invalid_output", usage=self.client.last_usage,
                error="storyboard processing failed", budget_policy=self.budget_policy,
            )
            raise
        self.store.finish_model_invocation(
            invocation, outcome="succeeded", usage=self.client.last_usage,
            response_value={"sha256": sha256(data).hexdigest()}, budget_policy=self.budget_policy,
        )
        return assets, {
            "model_id": self.client.model, "prompt_version": PROMPT_COMPILER_VERSION,
            "pipeline_id": pipeline_id, "archetype_id": recipe["archetype_id"],
            "overlay_version": profile["overlay_version"],
            "overlay": {"background": "transparent", "brand_text": profile["brand"], "labels": list(profile["labels"]),
                        "cta_namespace": profile["cta_namespace"],
                        "footer_cta_phrases": cta_phrases},
            "archetype_version": recipe["archetype_version"],
            "account_visual_profile_id": recipe["account_visual_profile_id"],
            "prompt_compiler_version": recipe["prompt_compiler_version"],
            "renderer_contract_id": recipe["renderer_contract_id"],
            "overlay_profile_id": recipe["overlay_profile_id"],
            "selection": recipe["selection"],
            "storyboard": {**spec["storyboard_plan"]["boards"][0], "columns": STORYBOARD_COLUMNS, "rows": STORYBOARD_ROWS,
                           "prompt_sha256": sha256(prompt.encode()).hexdigest(),
                           "raw": {"filename": raw.name, "mime_type": generated.mime_type,
                                   "extension": generated.extension, "bytes": len(data),
                                   "sha256": sha256(data).hexdigest()},
                           "split": split.metadata},
            "slides": provenance,
        }

    def _render_boards(self, run, package, spec, recipe, temporary, pipeline_id):
        plan = spec['storyboard_plan']
        if self.client is None:
            self.budget_policy = self.budget_policy or ModelBudgetPolicy.from_environment(configured_image_model(), image=True)
            self.client = VertexGeminiImageClient(max_output_tokens=self.budget_policy.phase_limits['image_rendering'][1])
        if self.budget_policy is not None and self.budget_policy.model_id != self.client.model:
            raise ValueError('image budget policy does not match configured model')
        assets, provenance, boards = [], [], []
        ctas = footer_cta_phrases(int(run['render_run_id']), plan['total_slides'], pipeline_id=pipeline_id)
        for board in plan['boards']:
            prompt = build_storyboard_prompt(package, recipe, pipeline_id=pipeline_id, board=board)
            invocation = self.store.begin_model_invocation(phase='image_rendering', table='render_runs',
                key='render_run_id', row=run, request_version='image_storyboard_request_v2',
                prompt_version=PROMPT_COMPILER_VERSION, schema_version='image_storyboard_paginated_v2',
                request_value={'prompt': prompt, 'board': board}, model_id=self.client.model,
                budget_policy=self.budget_policy, board_index=board['board_index'])
            try:
                generated = self.client.generate_image(prompt, aspect_ratio=board['provider_aspect_ratio'])
            except Exception:
                self.store.finish_model_invocation(invocation, outcome='transport_failed', usage=self.client.last_usage,
                    error='storyboard generation failed', budget_policy=self.budget_policy)
                raise
            try:
                if not isinstance(generated, GeneratedImage):
                    raise ValueError('image client did not preserve media metadata')
                split = split_equal_grid(generated.data, board)
                raw = temporary / f"raw-storyboard-{board['board_index']:02d}{generated.extension}"
                raw.write_bytes(generated.data)
                for cell, (ordinal, slide) in enumerate(zip(board['slide_indices'], split.slides)):
                    path = temporary / f'unit-{ordinal:02d}.png'
                    apply_overlays(slide, ordinal, plan['total_slides'], cta_phrase=ctas[ordinal-1],
                        pipeline_id=pipeline_id, role=package['visual_units'][ordinal-1]['role']).save(path, format='PNG')
                    asset = _asset(path, 'preview_png', ordinal, 1080, 1350)
                    assets.append(asset)
                    provenance.append(dict(ordinal=ordinal, board_index=board['board_index'], model_invocation_id=invocation,
                        source_cell=dict(row=cell // board['cols'] + 1, column=cell % board['cols'] + 1),
                        source_rectangle=split.metadata['source_rectangles'][cell], footer_cta=ctas[ordinal-1],
                        final=dict(filename=path.name, sha256=asset['sha256'])))
                boards.append(dict(**board, model_invocation_id=invocation, prompt_sha256=sha256(prompt.encode()).hexdigest(),
                    raw=dict(filename=raw.name, mime_type=generated.mime_type, extension=generated.extension,
                             bytes=len(generated.data), sha256=sha256(generated.data).hexdigest()), split=split.metadata))
            except Exception:
                self.store.finish_model_invocation(invocation, outcome='invalid_output', usage=self.client.last_usage,
                    error='storyboard processing failed', budget_policy=self.budget_policy)
                raise
            self.store.finish_model_invocation(invocation, outcome='succeeded', usage=self.client.last_usage,
                response_value={'sha256': sha256(generated.data).hexdigest()}, budget_policy=self.budget_policy)
        return assets, dict(model_id=self.client.model, prompt_version=PROMPT_COMPILER_VERSION,
            pipeline_id=pipeline_id, archetype_id=recipe['archetype_id'], archetype_version=recipe['archetype_version'],
            account_visual_profile_id=recipe['account_visual_profile_id'], prompt_compiler_version=recipe['prompt_compiler_version'],
            renderer_contract_id=recipe['renderer_contract_id'], overlay_profile_id=recipe['overlay_profile_id'],
            selection=recipe['selection'], boards=boards, slides=provenance,
            overlay_version=OVERLAY_PROFILES[pipeline_id]['overlay_version'],
            overlay=dict(background='transparent', brand_text=None, footer_cta_phrases=ctas))


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
