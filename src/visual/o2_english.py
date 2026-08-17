"""Deterministic HTML renderer for the o2 English idiom carousel profile."""

from html import escape
from pathlib import Path

from common.models import ContentPackage
from database.sqlite import Database


WIDTH = 1080
HEIGHT = 1920
PALETTES = {
    "neutral": {"background": "#F5F1E8", "text": "#1F2933", "highlight": "#C85A3F"},
}


def render_idiom_carousel_html(package: ContentPackage, output_directory: str | Path) -> list[Path]:
    spec = package.visual_spec
    if spec.get("profile_id") != "o2_english_idiom_carousel_v1":
        raise ValueError("Unsupported o2 English visual profile")
    palette = PALETTES["neutral"]
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    slides = spec.get("slides", [])
    files = []
    for index, slide in enumerate(slides, start=1):
        target = output_directory / f"slide{index}.html"
        target.write_text(_slide_html(slide, index, len(slides), palette), encoding="utf-8")
        files.append(target)
    return files


async def render_and_record_idiom_carousel_png(
    database: Database, package: ContentPackage, output_directory: str | Path,
) -> list[Path]:
    """Render every carousel slide to PNG and record the complete asset set."""
    if package.content_id is None:
        raise ValueError("A content package must be persisted before rendering")
    from playwright.async_api import async_playwright

    output_directory = Path(output_directory)
    html_files = render_idiom_carousel_html(package, output_directory / "html")
    png_directory = output_directory / "png"
    png_directory.mkdir(parents=True, exist_ok=True)
    png_files: list[Path] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            for index, html_file in enumerate(html_files, start=1):
                target = png_directory / f"slide{index}.png"
                await page.goto(html_file.resolve().as_uri())
                await page.screenshot(path=str(target), full_page=True)
                png_files.append(target)
        finally:
            await browser.close()
    database.mark_package_rendered_assets(
        package.content_id, [str(path) for path in png_files], required_asset_count=len(html_files),
    )
    return png_files


def _slide_html(slide: dict, index: int, total: int, palette: dict[str, str]) -> str:
    body = _body(slide)
    return f"""<!doctype html><html><head><meta charset=\"utf-8\"><style>
* {{ box-sizing: border-box; }} body {{ margin:0; width:{WIDTH}px; height:{HEIGHT}px; background:{palette['background']}; color:{palette['text']}; font-family:Arial,sans-serif; }}
.slide {{ position:relative; width:{WIDTH}px; height:{HEIGHT}px; padding:70px 80px; overflow:hidden; }}
.marker {{ display:flex; justify-content:space-between; font-size:32px; font-weight:800; }}
.watermark {{ position:absolute; bottom:110px; font-size:34px; font-weight:800; opacity:.48; }}
.hook {{ margin-top:260px; font-size:106px; line-height:1.16; font-weight:900; }}
.explanation {{ margin-top:260px; font-size:58px; line-height:1.18; font-weight:800; }}
.title {{ font-size:68px; font-weight:900; margin:0 0 70px; }}
.bubble {{ margin-top:150px; padding:58px; border:4px solid {palette['text']}; border-radius:56px; background:#fff; font-size:58px; line-height:1.18; font-weight:800; }}
.chat {{ width:710px; margin-top:100px; padding:44px; border:4px solid {palette['text']}; border-radius:42px; background:#fff; font-size:44px; line-height:1.18; font-weight:800; }} .chat.right {{ margin-left:210px; margin-top:160px; }}
</style></head><body><main class=\"slide\"><header class=\"marker\"><span>O2 ENGLISH</span><span>{index}/{total}</span></header>{body}<div class=\"watermark\">o2_english</div></main></body></html>"""


def _body(slide: dict) -> str:
    slide_type = slide["slide_type"]
    if slide_type == "hook":
        return f"<section class=\"hook\">{escape(slide['text'])}</section>"
    if slide_type == "explanation":
        return f"<section class=\"explanation\"><h1 class=\"title\">What it means</h1>{escape(slide['text'])}</section>"
    if slide_type == "use_case_monologue":
        label = escape(slide.get("label") or "You can say")
        return f"<section class=\"explanation\"><h1 class=\"title\">{label}</h1><div class=\"bubble\">“{escape(slide['text'])}”</div></section>"
    if slide_type == "use_case_dialogue":
        messages = slide["messages"]
        label = escape(slide.get("label") or "In conversation")
        return f"<section class=\"explanation\"><h1 class=\"title\">{label}</h1><div class=\"chat\">“{escape(messages[0])}”</div><div class=\"chat right\">“{escape(messages[1])}”</div></section>"
    raise ValueError(f"Unsupported slide type: {slide_type}")
