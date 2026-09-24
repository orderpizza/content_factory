"""Static local review gallery for isolated Pass 3 acceptance artifacts."""
from __future__ import annotations

from html import escape
from pathlib import Path


def _relative(target: Path, root: Path) -> str:
    return target.relative_to(root).as_posix()


def write_gallery(run_root: Path, results: list[dict[str, Any]]) -> Path:
    """Write a self-contained index without copying raw provider assets."""
    cards: list[str] = []
    for result in results:
        rendered = result.get("output", {}).get("image_rendering", {})
        manifest = rendered.get("manifest")
        if not manifest:
            continue
        case_dir = run_root / "cases" / result["case_id"] / f"attempt-{result['attempt']:02d}"
        slides = []
        for slide in manifest.get("slides", []):
            filename = slide.get("final", {}).get("filename")
            if filename:
                path = next(case_dir.glob(f"render-*/{filename}"), None)
                if path:
                    slides.append(f'<img loading="lazy" src="{escape(_relative(path, run_root))}" alt="Slide {slide.get("ordinal")}">')
        boards = []
        for board in manifest.get("boards", [manifest.get("storyboard")]):
            if not board:
                continue
            raw = board.get("raw", {}).get("filename")
            raw_path = None if not raw else next(case_dir.glob(f"render-*/{raw}"), None)
            label = f"board {board.get('board_index', 1)} · {board.get('cols', board.get('columns'))}×{board.get('rows')} · {board.get('provider_aspect_ratio')}"
            boards.append(f'<a href="{escape(_relative(raw_path, run_root))}">{escape(label)}</a>' if raw_path else escape(label))
        cards.append(
            '<article><h2>{}</h2><p>Status: {} · {} · {} · {} slides</p><p>{}</p><div class="slides">{}</div></article>'.format(
                escape(result["case_id"]), escape(result["status"]), escape(manifest.get("pipeline_id", "unknown")),
                escape(manifest.get("archetype_id", "unknown")), escape(str(manifest.get("storyboard_plan", {}).get("total_slides", 0))),
                " · ".join(boards), "".join(slides)))
    body = "\n".join(cards) or "<p>No completed image-rendering cases in this run.</p>"
    target = run_root / "gallery.html"
    target.write_text("""<!doctype html><meta charset=\"utf-8\"><title>Pass 3 visual acceptance</title>
<style>body{font-family:system-ui;margin:2rem;background:#f5f5f2;color:#162126}article{background:white;padding:1rem;margin:1rem 0;border-radius:10px}.slides{display:flex;gap:12px;overflow:auto}.slides img{width:216px;height:270px;object-fit:cover;border:1px solid #ddd}a{color:#135a8a}</style>
<h1>Pass 3 visual acceptance</h1><p>Local review evidence. Raw boards are original provider artifacts; slides are final overlaid PNGs.</p>""" + body)
    return target
