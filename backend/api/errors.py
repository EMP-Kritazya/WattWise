"""API errors and their `{ "detail": "text" }` responses (CONTRACTS.md §2)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# RuleError: fake-mode class; the engine's own RuleError is registered too when KITCHEN_IMPL=real (create_app).
from runtime.kitchen_factory import NotRecordedError, RuleError

__all__ = ["NoKitchenError", "NotFoundError", "NotRecordedError", "RuleError", "install_error_handlers"]


class NotFoundError(Exception):
    """Unknown id. Mapped to HTTP 404."""

    def __init__(self, kind: str, item_id: str):
        super().__init__(f"Unknown {kind} {item_id}")


class NoKitchenError(Exception):
    """No kitchen built yet (POST /api/kitchen first). Mapped to HTTP 404."""

    def __init__(self) -> None:
        super().__init__("No kitchen built yet; POST /api/kitchen first")


def _validation_text(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{where}: {err.get('msg', 'invalid')}" if where else str(err.get("msg", "invalid")))
    return "; ".join(parts) or "Invalid request"


def _detail(status: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


def install_error_handlers(app: FastAPI, engine_rule_error: type[Exception] = RuleError) -> None:
    @app.exception_handler(RequestValidationError)
    async def _invalid_body(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": _validation_text(exc)})

    for rule_error in {RuleError, engine_rule_error}:
        app.add_exception_handler(rule_error, _detail(422))
    app.add_exception_handler(NotFoundError, _detail(404))
    app.add_exception_handler(NoKitchenError, _detail(404))
    # STUB: fake mode or a not-yet-built feature has no answer for this request.
    app.add_exception_handler(NotRecordedError, _detail(501))
