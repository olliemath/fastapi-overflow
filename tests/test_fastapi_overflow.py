# Most of this file is vendored from the test suite in this fastapi PR:
# https://github.com/fastapi/fastapi/pull/12066/commits
# Copyright (c) 2024 Noah Klein
# Licensed under the MIT License
import asyncio
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import fastapi_overflow
from fastapi_overflow import _get_anti_deadlock_capacity_limiter


# Fire off 100 requests in parallel(ish) in order to create contention
# over the shared resource (simulating a fastapi server that interacts with
# a database connection pool).
def test_depends_deadlock_patch(patched_app: FastAPI):
    async def make_request(client: AsyncClient):
        await client.get("/deadlock")

    async def run_requests():
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://testserver"
        ) as aclient:
            tasks = [make_request(aclient) for _ in range(100)]
            await asyncio.gather(*tasks)

    asyncio.run(run_requests())


def test_set_thread_limit():
    # This needs a running event loop to set/check the thread limit
    async def inner():
        fastapi_overflow.set_thread_limit(10, anti_deadlock_reserve=2)
        assert _get_anti_deadlock_capacity_limiter().total_tokens == 8
        assert anyio.to_thread.current_default_thread_limiter().total_tokens == 10

    asyncio.run(inner())


@pytest.mark.parametrize(
    "limit, anti_deadlock_reserve, error_kind",
    [
        ("not an int", 2, TypeError),
        (10, "not an int", TypeError),
        (1, 0, ValueError),
        (10, 0, ValueError),
        (10, 9, ValueError),
    ],
)
def test_set_thread_limit_invalid_args(
    limit: Any, anti_deadlock_reserve: Any, error_kind: type[Exception]
):
    with pytest.raises(error_kind):
        fastapi_overflow.set_thread_limit(limit, anti_deadlock_reserve)


def test_run_in_threadpool():
    def blocking_function(x: int, y: int) -> int:
        return x + y

    async def inner():
        result = await fastapi_overflow.run_in_threadpool(blocking_function, 1, y=2)
        assert result == 3

    asyncio.run(inner())


def test_iterate_in_threadpool():
    async def inner():
        result = []
        async for item in fastapi_overflow.iterate_in_threadpool(range(5)):
            result.append(item)
        assert result == [0, 1, 2, 3, 4]

    asyncio.run(inner())
