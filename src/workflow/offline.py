"""Network refusal for single-threaded local operator commands."""
from contextlib import contextmanager, ExitStack
from unittest.mock import patch


@contextmanager
def offline_only():
    def refused(*args, **kwargs):
        raise RuntimeError("network access is forbidden in offline delivery commands")
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.create_connection", "socket.getaddrinfo", "socket.socket.sendto"):
            stack.enter_context(patch(target, refused))
        yield
