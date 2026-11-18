"""Network refusal for single-threaded local operator commands."""
from contextlib import contextmanager, ExitStack
from unittest.mock import patch
from contextvars import ContextVar

_OFFLINE = ContextVar("delivery_offline", default=False)

def require_offline():
    if not _OFFLINE.get():
        raise RuntimeError("offline integration requires the network-refusal boundary")

def is_offline():
    return _OFFLINE.get()



@contextmanager
def offline_only():
    def refused(*args, **kwargs):
        raise RuntimeError("network access is forbidden in offline delivery commands")
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.create_connection", "socket.getaddrinfo", "socket.socket.sendto"):
            stack.enter_context(patch(target, refused))
        token = _OFFLINE.set(True)
        try:
            yield
        finally:
            _OFFLINE.reset(token)


def readiness_eligible(status, facts_json):
    """Offline evidence stays degraded in SQLite and cannot authorize online work."""
    import json
    provenance = json.loads(facts_json).get("provenance")
    if provenance == "offline":
        return status == "degraded" and is_offline()
    return status == "ready"
