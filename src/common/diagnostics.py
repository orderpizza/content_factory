"""Bounded diagnostic redaction; never use this to rewrite human messages."""

import re


def safe_diagnostic(value: object, *, limit: int = 2000) -> str:
    text = str(value)
    # Diagnostic URLs are not evidence: drop them wholesale, including signed
    # queries, userinfo, fragments and credentials embedded in path segments.
    text = re.sub(r"https?://[^\s<>\"']+", "[redacted URL]", text, flags=re.I)
    text = re.sub(r"\b(?:Bearer|Basic)\s+[^\s,;\"']+", "[redacted authorization]", text, flags=re.I)
    text = re.sub(
        r"([\"']?(?:authorization|access[_-]?token|refresh[_-]?token|api[_-]?key|password|secret|signature|credential)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[redacted]", text, flags=re.I,
    )
    return text[:limit]
