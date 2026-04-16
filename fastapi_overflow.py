from collections.abc import (
    AsyncIterator,
    Callable,
    Iterable,
)
from contextlib import asynccontextmanager as asynccontextmanager
from typing import (
    Any,
    ParamSpec,
    TypeVar,
)

import anyio.to_thread
import fastapi.concurrency
import fastapi.dependencies.utils
import fastapi.routing
from anyio import CapacityLimiter
from fastapi._compat import ModelField
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import (
    EndpointContext,
    ResponseValidationError,
)
from fastapi.types import IncEx
from starlette.concurrency import (
    iterate_in_threadpool as _starlette_iterate_in_threadpool,
)
from starlette.concurrency import run_in_threadpool as _starlette_run_in_threadpool

_P = ParamSpec("_P")
_T = TypeVar("_T")
# The default threadpool in anyio is 40. This limiter keeps one thread
# for teardown tasks in order to prevent deadlocks when there is a pool
# of finite resources (e.g. database connections) which threads will block
# on trying to acquire.
_anti_deadlock_capacity_limiter = CapacityLimiter(39)


async def run_in_threadpool(
    func: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    async with _anti_deadlock_capacity_limiter:
        return await _starlette_run_in_threadpool(func, *args, **kwargs)


# NOTE: a separate function is required only because mypy dislikes trying to add
# a boolean flag along side the param spec
async def _run_in_threadpool_with_overflow(
    func: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Run a function in the thread pool, allowing it to use the overflow threads.

    Unless you know what you are doing you probably do not want to use this function.
    It has access to the entire thread pool, including the anti-deadlock reserve threads.
    """
    return await _starlette_run_in_threadpool(func, *args, **kwargs)


async def iterate_in_threadpool(iterator: Iterable[_T]) -> AsyncIterator[_T]:
    async with _anti_deadlock_capacity_limiter:
        async for item in _starlette_iterate_in_threadpool(iterator):
            yield item


def set_thread_limit(limit: int = 40, anti_deadlock_reserve: int = 1) -> None:
    """
    Set the maximum number of threads that can be used by the thread pool.

    This is a global setting that affects all calls to `run_in_threadpool` and
    `iterate_in_threadpool`.
    """
    if not isinstance(limit, int):
        raise TypeError("Thread limit must be an integer.")

    if not isinstance(anti_deadlock_reserve, int):
        raise TypeError("Anti deadlock reserve must be an integer.")

    if limit < 2:
        raise ValueError("Thread limit must be at least 2.")

    if not 0 < anti_deadlock_reserve < limit - 1:
        raise ValueError("Anti deadlock reserve must be between 0 and limit - 1.")

    anyio.to_thread.current_default_thread_limiter().total_tokens = limit
    _anti_deadlock_capacity_limiter.total_tokens = limit - anti_deadlock_reserve


def patch() -> None:
    """Patch both Starlette and FastAPI to use the anti-deadlock-aware thread pool."""
    fastapi.concurrency.run_in_threadpool = run_in_threadpool
    fastapi.concurrency.iterate_in_threadpool = iterate_in_threadpool  # type: ignore
    fastapi.routing.run_in_threadpool = run_in_threadpool
    fastapi.routing.iterate_in_threadpool = iterate_in_threadpool  # type: ignore
    fastapi.routing.serialize_response = _patched_serialize_response
    fastapi.dependencies.utils.run_in_threadpool = run_in_threadpool


# The below function has to be vendored from fastapi.routing and then patched back in,
# because we want to allow deadlock overflow.
# Derived from:
#   fastapi (https://github.com/tiangolo/fastapi)
#   Copyright (c) 2018 Sebastián Ramírez
#   Licensed under the MIT License
#
# Modifications:
#   Copyright (c) 2026 Oliver Margetts
async def _patched_serialize_response(
    *,
    field: ModelField | None = None,
    response_content: Any,
    include: IncEx | None = None,
    exclude: IncEx | None = None,
    by_alias: bool = True,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    is_coroutine: bool = True,
    endpoint_ctx: EndpointContext | None = None,
    dump_json: bool = False,
) -> Any:
    if field:
        if is_coroutine:
            value, errors = field.validate(response_content, {}, loc=("response",))
        else:
            value, errors = await _run_in_threadpool_with_overflow(
                field.validate,
                response_content,
                {},
                loc=("response",),
            )
        if errors:
            ctx = endpoint_ctx or EndpointContext()
            raise ResponseValidationError(
                errors=errors,
                body=response_content,
                endpoint_ctx=ctx,
            )
        serializer = field.serialize_json if dump_json else field.serialize
        return serializer(
            value,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )

    else:
        return jsonable_encoder(response_content)


__all__ = ["patch", "set_thread_limit", "run_in_threadpool", "iterate_in_threadpool"]
