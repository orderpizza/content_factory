"""Small, explicit provider-failure taxonomy shared by every Gemini boundary."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureDisposition(str, Enum):
    PROVIDER_TRANSIENT = "provider_transient"
    PROVIDER_TERMINAL = "provider_terminal"
    OUTPUT_CONTRACT = "output_contract"
    AMBIGUOUS_EXTERNAL = "ambiguous_external"
    LOCAL = "local"


@dataclass(frozen=True)
class ContractFailure(ValueError):
    """A terminal model-output or deterministic contract violation.

    The message remains useful in a local invocation trace, while ``code`` is
    intentionally short and safe for worker and dashboard diagnostics.
    """

    code: str
    message: str
    category: FailureDisposition = FailureDisposition.OUTPUT_CONTRACT

    def __str__(self) -> str:
        return self.message


class RetryScheduled(RuntimeError):
    """The durable state machine already released this claim for retry."""


def provider_status(error: BaseException) -> int | None:
    """Return a real SDK provider status only; never infer one from text."""
    try:
        from google.genai.errors import APIError
    except ImportError:
        return None
    if not isinstance(error, APIError):
        return None
    value = getattr(error, "code", None)
    value = value() if callable(value) else value
    return value if type(value) is int else None


def classify_failure(error: BaseException) -> FailureDisposition:
    """Classify replay safety conservatively.

    Recognized transient transports may replay within the common three-call
    limit. Their billing remains uncertain independently of retry eligibility.
    """
    if isinstance(error, ContractFailure):
        return error.category
    status = provider_status(error)
    if status in {429, 500, 502, 503, 504}:
        return FailureDisposition.PROVIDER_TRANSIENT
    if status is not None:
        return FailureDisposition.PROVIDER_TERMINAL
    try:
        from common.gemini import GeminiConfigurationError
    except ImportError:  # pragma: no cover - import safety for isolated tools
        GeminiConfigurationError = ()  # type: ignore[assignment]
    if isinstance(error, GeminiConfigurationError):
        return FailureDisposition.PROVIDER_TERMINAL
    import httpx
    if isinstance(error, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return FailureDisposition.PROVIDER_TRANSIENT
    if isinstance(error, OSError):
        return FailureDisposition.AMBIGUOUS_EXTERNAL
    return FailureDisposition.LOCAL


def safe_failure(
    *,
    stage: str,
    disposition: FailureDisposition,
    code: str,
    attempt: int | None = None,
    maximum: int = 3,
    retryable: bool = False,
    **details: Any,
) -> dict[str, Any]:
    """Produce structured, bounded, secret-free failure evidence."""
    value: dict[str, Any] = {
        "stage": stage,
        "category": disposition.value,
        "code": code,
        "retryable": retryable,
    }
    if attempt is not None:
        value["attempt"] = f"{attempt}/{maximum}"
    value.update({key: item for key, item in details.items() if item is not None})
    return value


def exception_diagnostic(stage: str, error: BaseException, attempt: int) -> dict[str, Any]:
    """Classify a provider-boundary exception without exposing its message."""
    disposition = classify_failure(error)
    code = (error.code if isinstance(error, ContractFailure) else
            f"http_{provider_status(error)}" if provider_status(error) is not None else
            type(error).__name__.casefold())
    return safe_failure(stage=stage, disposition=disposition, code=str(code), attempt=attempt,
                        retryable=disposition is FailureDisposition.PROVIDER_TRANSIENT)


def invocation_outcome(error: BaseException) -> str:
    """Map transport exceptions to ledger outcomes without retry assumptions."""
    disposition = classify_failure(error)
    if disposition is FailureDisposition.PROVIDER_TRANSIENT:
        return 'transport_failed'
    if disposition is FailureDisposition.PROVIDER_TERMINAL:
        return 'provider_terminal'
    if disposition is FailureDisposition.AMBIGUOUS_EXTERNAL:
        return 'ambiguous_outcome'
    return 'parse_failed' if 'json' in str(error).casefold() else 'invalid_output'
