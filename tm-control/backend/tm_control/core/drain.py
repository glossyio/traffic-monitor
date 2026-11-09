"""Read the rest of a refused upload before answering it.

nginx streams model uploads to tm-control as they arrive (`proxy_request_buffering off`). When tm-control answers
before it has read the whole body, as any refusal does, uvicorn closes the connection while nginx is still sending,
and nginx answers 502 in place of tm-control's answer. So on the upload path this middleware reads and discards
whatever body is left before the response starts, and nginx passes the real answer on.
"""

import logging

log = logging.getLogger(__name__)


class DrainMiddleware:
    """A pure ASGI middleware for HTTP requests whose path starts with `prefix`; everything else passes through.

    It discards at most `bound` bytes; past that, or when the client disconnects, it stops and answers anyway. A
    request whose body the app read to the end is left alone. Nothing it reads is kept or written anywhere."""

    def __init__(self, app, *, prefix: str, bound: int):
        self.app = app
        self.prefix = prefix
        self.bound = bound

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            await self.app(scope, receive, send)
            return
        body_done = False

        def note(message) -> None:
            nonlocal body_done
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                body_done = True

        async def noting_receive():
            message = await receive()
            note(message)
            return message

        async def draining_send(message):
            if message["type"] == "http.response.start" and not body_done:
                discarded = 0
                while not body_done and discarded <= self.bound:
                    rest = await receive()
                    note(rest)
                    discarded += len(rest.get("body", b""))
                if not body_done:
                    log.info("answering %s %s with its body still unread past %d bytes",
                             scope["method"], scope["path"], self.bound)
            await send(message)

        await self.app(scope, noting_receive, draining_send)
