"""Load an optional local .env file without overriding the process environment."""

from __future__ import annotations

from pathlib import Path
import os
import re


KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class EnvironmentFileError(ValueError):
    """Raised for a malformed local environment file without exposing values."""


def load_environment_file(path: str | Path) -> bool:
    """Load KEY=VALUE records if present; existing environment values always win."""

    environment_path = Path(path)
    if not environment_path.exists():
        return False
    if not environment_path.is_file():
        raise EnvironmentFileError(f"Environment path is not a regular file: {environment_path}")
    try:
        lines = environment_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise EnvironmentFileError(f"Cannot read environment file: {environment_path}") from error
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise EnvironmentFileError(
                f"Malformed environment assignment at line {line_number}"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if KEY.fullmatch(key) is None:
            raise EnvironmentFileError(
                f"Invalid environment key at line {line_number}"
            )
        value = value.strip()
        if value[:1] in {"'", '"'}:
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise EnvironmentFileError(
                    f"Unclosed quoted value at line {line_number}"
                )
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)
    return True
