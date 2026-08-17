"""Deterministic HTML renderer for the POC visual asset."""

from html import escape
from pathlib import Path

from common.models import ContentPackage
from database.sqlite import Database
from visual.theme import THEME


class VisualRenderer:
    width = 1080
    height = 1350

    def render_html(self, package: ContentPackage, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        spec = package.visual_spec
        title = escape(str(spec.get("title", package.title)))
        body = escape(str(spec.get("body", package.body))).replace("\n", "<br>")
        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; width: {self.width}px; height: {self.height}px; background: {THEME['background']}; color: {THEME['text']}; font-family: {THEME['font_family']}; padding: {THEME['padding']}px; }}
.accent {{ width: 96px; height: 12px; background: {THEME['accent']}; margin-bottom: 100px; }}
h1 {{ font-size: 76px; line-height: 1.05; margin: 0 0 64px; }}
.body {{ font-size: 36px; line-height: 1.45; }}
</style></head><body>
<div class="accent"></div><h1>{title}</h1><div class="body">{body}</div>
</body></html>"""
        path.write_text(html, encoding="utf-8")
        return path

    async def render_png(self, package: ContentPackage, html_path: str | Path, output_path: str | Path) -> Path:
        from playwright.async_api import async_playwright

        html_path = self.render_html(package, html_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": self.width, "height": self.height}, device_scale_factor=1)
            await page.goto(html_path.resolve().as_uri())
            await page.screenshot(path=str(output_path), full_page=True)
            await browser.close()
        return output_path

    async def render_and_record_png(self, database: Database, package: ContentPackage, html_path: str | Path, output_path: str | Path) -> Path:
        if package.content_id is None:
            raise ValueError("A content package must be persisted before rendering")
        output_path = await self.render_png(package, html_path, output_path)
        database.mark_package_rendered(package.content_id, str(output_path))
        return output_path
