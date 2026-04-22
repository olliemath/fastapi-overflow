import functools
from collections.abc import Callable
from contextlib import asynccontextmanager as asynccontextmanager
from typing import (
    Any,
    ParamSpec,
    TypeVar,
)

import anyio.to_thread
import fastapi.routing
from anyio import CapacityLimiter
from fastapi._compat import ModelField
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import (
    EndpointContext,
    ResponseValidationError,
)
from fastapi.types import IncEx

_P = ParamSpec("_P")
_T = TypeVar("_T")
# In order to avoid deadlocks, separate capacity limiters are needed for acquiring
# and releasing threads. This limiter is used to ensure we always have some threads
# releasing resources (like database connections) back to the pool.
_release_capacity_limiter: CapacityLimiter = CapacityLimiter(5)


# NOTE: a separate function is required only because mypy dislikes trying to add
# a boolean flag along side the param spec
async def run_in_release_threadpool(
    func: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Run a function in the thread pool, allowing it to use the "release" threads.

    Unless you know what you are doing you probably do not want to use this function.
    It has access to the capacity used exclusively for releasing resources, which is
    separate from the main thread pool to avoid deadlocks.
    """
    func = functools.partial(func, *args, **kwargs)
    return await anyio.to_thread.run_sync(func, limiter=_release_capacity_limiter)


def set_thread_limit(default_limit: int = 40, release_limit: int = 5) -> None:
    """
    Set the maximum number of threads that can be used by the thread pool.

    The `default_limit` parameter controls the number of threads available for general use,
    while the `release_limit` parameter controls the number of threads reserved for releasing
    resources. These are separate to prevent deadlocks.
    """
    if not isinstance(default_limit, int):
        raise TypeError("Default limit must be an integer.")

    if not isinstance(release_limit, int):
        raise TypeError("Release limit must be an integer.")

    if default_limit < 1 or release_limit < 1:
        raise ValueError("Thread limits must be at least 1.")

    anyio.to_thread.current_default_thread_limiter().total_tokens = default_limit
    _release_capacity_limiter.total_tokens = release_limit


def patch() -> None:
    """Patch both Starlette and FastAPI to use the anti-deadlock-aware thread pool."""
    fastapi.routing.serialize_response = _patched_serialize_response


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
            value, errors = await run_in_release_threadpool(
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


__all__ = ["patch", "set_thread_limit", "run_in_release_threadpool"]
