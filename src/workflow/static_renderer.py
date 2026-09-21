"""Local HTML/Playwright renderer for immutable v2 review packages."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import base64
import json
import os
import shutil
import tempfile
import time

from PIL import Image
import PIL
from playwright.sync_api import sync_playwright

from .store import WorkflowStore
from .workers import local_operation
from .visual_registry import THEMES, TYPOGRAPHY, validate_recipe, validate_unit_layouts
from .visual_primitives import PRIMITIVE_CSS, footer, render_layout


PROFILES = {
    "static_instagram_review_v1": {"width": 1080, "height": 1350, "minimum": 5, "maximum": 8},
    "static_x_review_v1": {"width": 1200, "height": 675, "minimum": 1, "maximum": 1},
    "static_instagram_delivery_v1": {"width": 1080, "height": 1350, "minimum": 5, "maximum": 8},
    "static_x_delivery_v1": {"width": 1200, "height": 675, "minimum": 1, "maximum": 1},
}


class LayoutOverflow(ValueError):
    """An explicit layout failure eligible for registered fallback planning."""


class StaticVisualRenderer:
    """Render exact local review assets; never perform delivery."""

    def __init__(
        self,
        store: WorkflowStore,
        artifact_root: str | Path,
        *,
        instance_id: str = "renderer-html-playwright",
        production: bool = False,
    ):
        self.store = store
        self.artifact_root = Path(artifact_root).resolve()
        self.instance_id = instance_id
        self.production = production

    def run_once(self) -> int | None:
        run = self.store.claim(
            "render_runs", "render_run_id", self.instance_id, lease_seconds=600
        )
        if run is None:
            return None
        return self._process(run)

    @local_operation("render_runs", "render_run_id")
    def _process(self, run: Any) -> int | None:
        package_row = self.store.connection.execute(
            "SELECT cp.package_json,cp.content_hash,vr.recipe_json FROM content_packages cp "
            "JOIN visual_recipes vr ON vr.visual_recipe_id=? WHERE cp.content_package_id=?",
            (run["visual_recipe_id"], run["content_package_id"]),
        ).fetchone()
        if package_row is None:
            raise ValueError("render run references a missing ContentPackage")
        package = json.loads(package_row["package_json"])
        spec = _render_spec(package, production=self.production)
        recipe = validate_recipe(json.loads(package_row["recipe_json"]), production=self.production)
        validate_unit_layouts(recipe, [unit["role"] for unit in spec["units"]])
        font = self._production_font() if self.production else None

        self.artifact_root.mkdir(parents=True, exist_ok=True)
        final_directory = self.artifact_root / f"render-{run['render_run_id']}"
        if final_directory.exists():
            quarantine_root = self.artifact_root / "quarantine"
            quarantine_root.mkdir(parents=True, exist_ok=True)
            quarantine = quarantine_root / (
                f"render-{run['render_run_id']}-uncommitted-{time.time_ns()}"
            )
            final_directory.rename(quarantine)
            self.store.record_artifact_quarantine(
                int(run["render_run_id"]), final_directory, quarantine,
                "promoted directory existed without a succeeded render record",
            )
        temporary = Path(tempfile.mkdtemp(
            prefix=f"render-{run['render_run_id']}-", suffix=".tmp", dir=self.artifact_root
        ))
        assets: list[dict[str, Any]] = []
        browser_version = "unknown"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                browser_version = browser.version
                try:
                    page = browser.new_page(
                        viewport={"width": spec["width"], "height": spec["height"]},
                        device_scale_factor=1,
                    )
                    for ordinal, unit in enumerate(spec["units"], start=1):
                        html_path = temporary / f"unit-{ordinal:02d}.html"
                        png_path = temporary / f"unit-{ordinal:02d}.png"
                        jpeg_path = temporary / f"unit-{ordinal:02d}.jpg"
                        html_path.write_text(
                            _unit_html(unit, spec, recipe, ordinal, len(spec["units"]), font=font),
                            encoding="utf-8",
                        )
                        page.goto(html_path.resolve().as_uri(), wait_until="load")
                        page.evaluate("document.fonts.ready")
                        layout_ok = page.evaluate(
                            "Array.from(document.querySelectorAll('[data-bound]')).every("
                            "node => node.scrollHeight <= node.clientHeight && "
                            "node.scrollWidth <= node.clientWidth)"
                        )
                        if not layout_ok:
                            raise LayoutOverflow(f"rendered unit {ordinal} overflows its template bounds")
                        page.screenshot(path=str(png_path), type="png")
                        with Image.open(png_path) as source:
                            if source.size != (spec["width"], spec["height"]):
                                raise ValueError(f"rendered unit {ordinal} has incorrect dimensions")
                            source.convert("RGB").save(
                                jpeg_path,
                                format="JPEG",
                                quality=92,
                                optimize=False,
                                progressive=False,
                            )
                        assets.extend([
                            _asset(html_path, "preview_html", ordinal, spec["width"], spec["height"]),
                            _asset(png_path, "preview_png", ordinal, spec["width"], spec["height"]),
                            _asset(jpeg_path, "delivery_jpeg", ordinal, spec["width"], spec["height"]),
                        ])
                finally:
                    browser.close()
            for path in temporary.iterdir():
                if path.is_file():
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            _fsync_directory(temporary)
            temporary.rename(final_directory)
            _fsync_directory(self.artifact_root)
            for asset in assets:
                asset["path"] = str(final_directory / Path(asset["path"]).name)
            manifest = {
                "schema_version": "render_manifest_v1",
                "renderer": "html_playwright_v1",
                "profile_id": spec["profile_id"],
                "visual_recipe_hash": sha256(package_row["recipe_json"].encode("utf-8")).hexdigest(),
                "visual_registry_release": recipe["registry_release"],
                "visual_registry_fingerprint": recipe["registry_fingerprint"],
                "content_hash": package_row["content_hash"],
                "browser_version": browser_version,
                "pillow_version": PIL.__version__,
                "review_only": not self.production,
                "profile_version": (
                    None if font is None else font["profile_version"]
                ),
                "template_version": (
                    "static_social_template_review_v1"
                    if font is None else font["template_version"]
                ),
                "font_sha256": None if font is None else font["font_sha256"],
                "assets": assets,
            }
            return self.store.complete_render(run, manifest, assets)
        except LayoutOverflow as error:
            if temporary.exists():
                shutil.rmtree(temporary)
            return self.store.schedule_visual_fallback(run, reason="registered composition overflow")
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _production_font(self) -> dict[str, str]:
        row = self.store.connection.execute(
            "SELECT pc.configuration_json FROM production_configurations pc "
            "JOIN configuration_activations a ON a.configuration_release_id=pc.configuration_release_id "
            "AND a.scope_key='global' AND a.status='active'"
        ).fetchone()
        if row is None:
            raise ValueError("active production renderer configuration is missing")
        profile = json.loads(row["configuration_json"]).get("renderer_profile")
        if not isinstance(profile, dict):
            raise ValueError("production renderer profile is missing")
        configured = Path(str(profile.get("font_path", "")))
        if configured.is_symlink():
            raise ValueError("production font file cannot be a symbolic link")
        path = configured.resolve(strict=True)
        if path.stat().st_size > 20_000_000:
            raise ValueError("production font file is invalid")
        data = path.read_bytes()
        actual = sha256(data).hexdigest()
        if actual != profile.get("font_sha256"):
            raise ValueError("production font fingerprint changed after profile approval")
        suffix = path.suffix.casefold()
        mime = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff",
                ".woff2": "font/woff2"}.get(suffix)
        if mime is None:
            raise ValueError("production font format is unsupported")
        return {**profile, "data_url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}


def _render_spec(package: Any, *, production: bool = False) -> dict[str, Any]:
    if not isinstance(package, dict):
        raise ValueError("render package is invalid")
    platform = package.get("platform")
    profile_id = ("static_instagram_delivery_v1" if production else "static_instagram_review_v1") if platform == "instagram" else ("static_x_delivery_v1" if production else "static_x_review_v1") if platform == "x" else None
    profile = PROFILES.get(profile_id)
    if profile is None or package.get("delivery_ready") is not production:
        raise ValueError("package/platform renderer safety mode does not match")
    units = package.get("visual_units")
    if not isinstance(units, list) or not profile["minimum"] <= len(units) <= profile["maximum"]:
        raise ValueError("visual unit count does not match the selected profile")
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != {"role", "title", "body", "claim_ids"}:
            raise ValueError("visual unit has an invalid shape")
        if unit["role"] not in {"hook", "explanation", "example", "takeaway"}:
            raise ValueError("visual unit role is unsupported")
        if not all(isinstance(unit[field], str) and unit[field] for field in ("title", "body")):
            raise ValueError("visual unit text is missing")
        if not isinstance(unit["claim_ids"], list):
            raise ValueError("visual unit claim mapping is invalid")
    return {"profile_id": profile_id, "width": profile["width"], "height": profile["height"], "units": units}


def _unit_html(
    unit: dict[str, Any],
    spec: dict[str, Any],
    recipe: dict[str, Any],
    ordinal: int,
    total: int,
    *,
    font: dict[str, str] | None = None,
) -> str:
    font_face = "" if font is None else (
        "@font-face { font-family: 'ContentFactoryPinned'; src: url('"
        + font["data_url"] + "'); font-weight: 100 900; font-style: normal; }"
    )
    family = TYPOGRAPHY[recipe["typography_id"]]["family"] if font is None else "'ContentFactoryPinned', sans-serif"
    theme = THEMES[recipe["theme_id"]]
    layout_variant = recipe["unit_layouts"][ordinal - 1]["variant"]
    decorations = recipe["decorations"]
    decoration = ("radial-gradient(" + theme["accent"] + " 1px, transparent 1px) 0 0/18px 18px"
                  if "subtle_dots_v1" in decorations else
                  "linear-gradient(135deg, transparent 0 72%, " + theme["accent"] + "22 72% 73%, transparent 73%)"
                  if "soft_wave_v1" in decorations else "none")
    content = render_layout(unit, layout_variant)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
{font_face}
{PRIMITIVE_CSS}
:root {{ --bg:{theme['background']}; --surface:{theme['surface']}; --text:{theme['text']}; --muted:{theme['muted']}; --accent:{theme['accent']}; --font:{family}; --tracking:{TYPOGRAPHY[recipe['typography_id']]['tracking']}; --decoration:{decoration}; }}
</style></head><body><div class="frame">{content}{footer(ordinal, total)}</div></body></html>"""


def _asset(path: Path, role: str, ordinal: int, width: int, height: int) -> dict[str, Any]:
    data = path.read_bytes()
    mime = {"preview_html": "text/html", "preview_png": "image/png", "delivery_jpeg": "image/jpeg"}[role]
    return {
        "role": role,
        "ordinal": ordinal,
        "path": str(path),
        "mime": mime,
        "width": width,
        "height": height,
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
