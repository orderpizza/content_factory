"""Canonical contract lookup for checkouts and installed distributions."""

from importlib.resources import files
from pathlib import Path


def contract_path(name: str):
    """Keep checkout SQL authoritative; wheels carry byte-identical build copies."""
    if Path(name).name != name or not name.endswith(".sql"):
        raise ValueError("expected a SQL contract filename")
    checkout = Path(__file__).resolve().parents[2] / "docs" / "contracts" / name
    return checkout if checkout.is_file() else files(__package__).joinpath("contracts", name)
