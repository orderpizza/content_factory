"""Integer-micro-USD admission policy for opt-in production Gemini calls."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from hashlib import sha256
from typing import Mapping
import json
import os


class ModelBudgetConfigurationError(ValueError):
    """Raised before a model call when priced admission is incomplete."""


class ModelBudgetExceeded(RuntimeError):
    """Raised after a blocked admission decision is durably audited."""


DEFAULT_PHASE_LIMITS = {
    "intake": (8_000, 2_000),
    "determination": (12_000, 4_000),
    "generation": (12_000, 4_000),
    # Carousel JSON and thinking share the provider output-token allowance.
    "adaptation": (12_000, 8_000),
}


def _decimal(name: str, environment: Mapping[str, str]) -> Decimal:
    raw = environment.get(name)
    if raw is None or not raw.strip():
        raise ModelBudgetConfigurationError(f"{name} is required for production model admission")
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ModelBudgetConfigurationError(f"{name} must be a decimal number") from error
    if not value.is_finite() or value <= 0:
        raise ModelBudgetConfigurationError(f"{name} must be greater than zero")
    return value


def _micro_usd(value: Decimal) -> int:
    return int((value * Decimal(1_000_000)).to_integral_value(rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class ModelBudgetPolicy:
    model_id: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    daily_warning_micro_usd: int
    daily_hard_micro_usd: int
    job_hard_micro_usd: int
    phase_limits: Mapping[str, tuple[int, int]]

    @classmethod
    def from_environment(
        cls, model_id: str, environment: Mapping[str, str] | None = None
    ) -> "ModelBudgetPolicy":
        values = os.environ if environment is None else environment
        input_rate = _decimal("GEMINI_INPUT_COST_PER_MILLION_USD", values)
        output_rate = _decimal("GEMINI_OUTPUT_COST_PER_MILLION_USD", values)
        warning = _micro_usd(_decimal("GEMINI_DAILY_WARNING_USD", values))
        hard = _micro_usd(_decimal("GEMINI_DAILY_HARD_LIMIT_USD", values))
        job = _micro_usd(_decimal("GEMINI_JOB_HARD_LIMIT_USD", values))
        if warning > hard:
            raise ModelBudgetConfigurationError("Gemini daily warning cannot exceed the hard limit")
        limits: dict[str, tuple[int, int]] = {}
        for phase, defaults in DEFAULT_PHASE_LIMITS.items():
            input_limit = int(values.get(
                f"GEMINI_{phase.upper()}_MAX_INPUT_TOKENS", str(defaults[0])
            ))
            output_limit = int(values.get(
                f"GEMINI_{phase.upper()}_MAX_OUTPUT_TOKENS", str(defaults[1])
            ))
            if input_limit < 1 or output_limit < 1:
                raise ModelBudgetConfigurationError(f"Gemini {phase} token maxima must be positive")
            limits[phase] = (input_limit, output_limit)
        return cls(model_id, input_rate, output_rate, warning, hard, job, limits)

    @property
    def fingerprint(self) -> str:
        value = {
            "policy": "gemini_budget_v1",
            "model_id": self.model_id,
            "input_usd_per_million": str(self.input_usd_per_million),
            "output_usd_per_million": str(self.output_usd_per_million),
            "daily_warning_micro_usd": self.daily_warning_micro_usd,
            "daily_hard_micro_usd": self.daily_hard_micro_usd,
            "job_hard_micro_usd": self.job_hard_micro_usd,
            "phase_limits": dict(self.phase_limits),
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    def worst_case(self, phase: str) -> tuple[int, int, int]:
        try:
            input_tokens, output_tokens = self.phase_limits[phase]
        except KeyError as error:
            raise ModelBudgetConfigurationError(f"no Gemini token policy exists for phase {phase}") from error
        amount = (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ).to_integral_value(rounding=ROUND_CEILING)
        return input_tokens, output_tokens, int(amount)

    def actual_cost(self, input_tokens: int, output_tokens: int) -> int:
        amount = (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ).to_integral_value(rounding=ROUND_CEILING)
        return max(0, int(amount))
