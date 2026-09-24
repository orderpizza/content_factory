"""Production-backed acceptance adapters.

Adapters only seed isolated persisted inputs and invoke the production workers;
they deliberately do not reproduce prompts or response schemas.
"""

from .pipeline import execute_case

__all__ = ["execute_case"]
