"""Fail-closed retirement boundary for superseded operational entrypoints."""


class RetiredOperationError(RuntimeError):
    """The legacy operation cannot meet current approval/accounting contracts."""


def refuse_legacy_operation(operation: str) -> None:
    raise RetiredOperationError(
        f"{operation} is retired. Use the versioned local detection/workflow commands. "
        "Production model calls, delivery and retention require their forward safety contracts; "
        "there is no environment flag to bypass this boundary."
    )
