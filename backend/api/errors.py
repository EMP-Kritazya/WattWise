"""API errors and their `{ "detail": "text" }` responses (CONTRACTS.md §2)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

try:
    from engine import RuleError
except ImportError:  # STUB: engine package not on this branch yet; same name and meaning as the facade's RuleError

    class RuleError(Exception):
        """Unsafe limits or moves. Mapped to HTTP 422."""


class NotFoundError(Exception):
    """Unknown id. Mapped to HTTP 404."""

    def __init__(self, kind: str, item_id: str):
        super().__init__(f"Unknown {kind} {item_id}")


class NotRecordedError(Exception):
    """STUB: the fixture service has no recorded answer for this request. Mapped to HTTP 501."""


def _validation_text(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{where}: {err.get('msg', 'invalid')}" if where else str(err.get("msg", "invalid")))
    return "; ".join(parts) or "Invalid request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _invalid_body(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": _validation_text(exc)})

    @app.exception_handler(RuleError)
    async def _rule_error(_: Request, exc: RuleError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(NotRecordedError)
    async def _not_recorded(_: Request, exc: NotRecordedError) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": str(exc)})
