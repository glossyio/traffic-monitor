"""The API's one error shape, {"error": {"code", "message", "detail"}}, for every error the app returns.

Handlers log the exception class and the request path, never bodies, headers, or cookies.
"""

import logging
from http import HTTPStatus

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)

# Codes for errors raised by the framework (routing, validation) rather than as ApiError.
HTTP_STATUS_CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation",
    429: "rate_limited",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail=None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        self.headers = headers  # such as Retry-After on a 429


def error_response(status, code, message, detail=None, headers=None):
    body = {"error": {"code": code, "message": message, "detail": detail}}
    return JSONResponse(body, status_code=status, headers=headers)


def _log(request, exc, status):
    level = logging.ERROR if status >= 500 else logging.DEBUG
    log.log(level, "%s %s on %s", status, type(exc).__name__, request.url.path)


async def _api_error(request, exc: ApiError):
    _log(request, exc, exc.status)
    return error_response(exc.status, exc.code, exc.message, exc.detail, headers=exc.headers)


async def _validation_error(request, exc: RequestValidationError):
    _log(request, exc, 422)
    # loc, msg, and type only: the input and context can hold what the client sent, such as a password
    detail = [{"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]} for item in exc.errors()]
    return error_response(422, "validation", "The request is not valid.", detail)


async def _http_exception(request, exc: HTTPException):
    _log(request, exc, exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    detail = None if isinstance(exc.detail, str) else exc.detail
    code = HTTP_STATUS_CODES.get(exc.status_code, "error")
    return error_response(exc.status_code, code, message, detail, headers=getattr(exc, "headers", None))


async def _unhandled(request, exc: Exception):
    _log(request, exc, 500)
    return error_response(500, "internal", "Something went wrong in tm-control.")


def install_error_handlers(app):
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_exception)
    app.add_exception_handler(Exception, _unhandled)
