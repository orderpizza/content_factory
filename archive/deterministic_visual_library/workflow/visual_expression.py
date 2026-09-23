"""Closed content and local-asset rules for the expression-breakdown archetype."""
from __future__ import annotations

from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AVATAR_ROOT = REPOSITORY_ROOT / "assets" / "visual" / "avatars"
MANIFEST_PATH = AVATAR_ROOT / "manifest.json"
REQUIRED_SPEAKERS = ("speaker_01", "speaker_02")
EXPECTED_ROLES = ("hook", "explanation", "explanation", "example", "example", "takeaway")


def headline_scale(value: str) -> str:
    """Return a bounded, inspectable headline scale; never a free-form shrink."""
    words, characters = len(value.split()), len(value.strip())
    if words <= 3 and characters <= 20:
        return "headline_xl"
    if words <= 5 and characters <= 38:
        return "headline_l"
    return "headline_m"


def _lines(value: str) -> list[str]:
    return [line.strip(" •-\t") for line in value.splitlines() if line.strip(" •-\t")]


def _word_count(value: str) -> int:
    return len(value.split())


def validate_expression_units(units: list[Mapping[str, Any]]) -> None:
    """Validate the intentionally narrow six-slide content capacity contract."""
    if [unit.get("role") for unit in units] != list(EXPECTED_ROLES):
        raise ValueError("expression breakdown requires its registered six-slide role sequence")
    hook, meaning, checklist, examples, dialogue, takeaway = units
    if _word_count(str(hook["title"])) > 5 or _word_count(str(hook["body"])) > 20:
        raise ValueError("expression hook exceeds its readable content capacity")
    meaning_lines = _lines(str(meaning["body"]))
    if not meaning_lines or _word_count(meaning_lines[0]) > 35 or any(_word_count(item) > 18 for item in meaning_lines[1:]):
        raise ValueError("expression definition exceeds its readable content capacity")
    checklist_lines = _lines(str(checklist["body"]))
    if not 3 <= len(checklist_lines) <= 4 or any(_word_count(item) > 14 for item in checklist_lines):
        raise ValueError("expression checklist must contain three or four concise rows")
    example_lines = _lines(str(examples["body"]))
    if len(example_lines) != 2 or any(_word_count(item) > 22 for item in example_lines):
        raise ValueError("expression examples require exactly two concise primary examples")
    dialogue_lines = _lines(str(dialogue["body"]))
    if not 3 <= len(dialogue_lines) <= 4 or any(_word_count(item) > 16 for item in dialogue_lines):
        raise ValueError("expression dialogue requires three or four concise turns")
    takeaway_lines = _lines(str(takeaway["body"]))
    if not 2 <= len(takeaway_lines) <= 3 or any(_word_count(item) > 16 for item in takeaway_lines):
        raise ValueError("expression takeaway requires two or three concise recap points")


def _manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("visual avatar manifest is unavailable") from error
    if set(value) != {"schema_version", "avatars"} or value["schema_version"] != "visual_avatar_manifest_v1" or not isinstance(value["avatars"], dict):
        raise ValueError("visual avatar manifest has an invalid shape")
    return value


def _placeholder(asset_id: str) -> dict[str, str]:
    initial = "A" if asset_id.endswith("01") else "B"
    return {"asset_id": asset_id, "mode": "placeholder", "initial": initial}


def resolve_dialogue_avatars(*, production: bool, avatar_root: Path = AVATAR_ROOT) -> list[dict[str, str]]:
    """Resolve approved PNGs or stable review placeholders without network access."""
    avatar_root = avatar_root.resolve()
    manifest = _manifest(avatar_root / "manifest.json")
    result: list[dict[str, str]] = []
    for asset_id in REQUIRED_SPEAKERS:
        descriptor = manifest["avatars"].get(asset_id)
        if not isinstance(descriptor, dict) or set(descriptor) != {"file", "orientation", "mood"}:
            raise ValueError("visual avatar manifest entry is invalid")
        filename = descriptor["file"]
        if not isinstance(filename, str) or filename != Path(filename).name or not filename.endswith(".png"):
            raise ValueError("visual avatar path is invalid")
        candidate = avatar_root / filename
        if not candidate.exists():
            if production:
                raise ValueError(f"production expression render is missing approved avatar {asset_id}")
            result.append(_placeholder(asset_id))
            continue
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("visual avatar file cannot be a symbolic link")
        resolved = candidate.resolve(strict=True)
        if resolved.parent != avatar_root or resolved.suffix.casefold() != ".png":
            raise ValueError("visual avatar file is outside the approved asset root")
        data = resolved.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("visual avatar file is not a PNG")
        result.append({"asset_id": asset_id, "mode": "asset", "relative_path": f"assets/visual/avatars/{filename}",
                       "sha256": sha256(data).hexdigest(), "data_url": "data:image/png;base64," + b64encode(data).decode("ascii"),
                       "orientation": str(descriptor["orientation"])})
    return result


def avatar_provenance(avatars: list[Mapping[str, str]]) -> list[dict[str, str]]:
    return [{key: avatar[key] for key in ("asset_id", "relative_path", "sha256")} for avatar in avatars if avatar.get("mode") == "asset"]
