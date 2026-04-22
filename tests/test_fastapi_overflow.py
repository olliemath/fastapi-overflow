# Most of this file is vendored from the test suite in this fastapi PR:
# https://github.com/fastapi/fastapi/pull/12066/commits
# Copyright (c) 2024 Noah Klein
# Licensed under the MIT License
import asyncio
import time
from typing import Any

import anyio
import fastapi.concurrency
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import fastapi_overflow


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


@pytest.mark.anyio
@pytest.mark.usefixtures("release_capacity_limiter")
async def test_set_thread_limit():
    fastapi_overflow.set_thread_limit(10, release_limit=2)
    assert fastapi_overflow._release_capacity_limiter.total_tokens == 2
    assert anyio.to_thread.current_default_thread_limiter().total_tokens == 10


@pytest.mark.parametrize(
    "limit, release_limit, error_kind",
    [
        ("not an int", 2, TypeError),
        (10, "not an int", TypeError),
        (1, 0, ValueError),
        (0, 1, ValueError),
        (-1, -1, ValueError),
    ],
)
def test_set_thread_limit_invalid_args(
    limit: Any, release_limit: Any, error_kind: type[Exception]
):
    with pytest.raises(error_kind):
        fastapi_overflow.set_thread_limit(limit, release_limit)


@pytest.mark.anyio
@pytest.mark.usefixtures("release_capacity_limiter")
async def test_run_in_release_threadpool():
    def blocking_function(x: int, y: int) -> int:
        return x + y

    result = await fastapi_overflow.run_in_release_threadpool(blocking_function, 1, y=2)
    assert result == 3


@pytest.mark.anyio
@pytest.mark.usefixtures("release_capacity_limiter")
async def test_competing_acquire_release() -> None:
    """Check that the main threadpool does not block the release threadpool."""
    pool_size = int(anyio.to_thread.current_default_thread_limiter().total_tokens)
    acquirable = False
    acquired: list[bool] = []

    def acquire() -> None:
        while not acquirable:
            time.sleep(0.001)
        acquired.append(True)

    def release() -> None:
        nonlocal acquirable
        time.sleep(0.001)
        acquirable = True

    async with anyio.create_task_group() as tg:
        for _ in range(pool_size):
            tg.start_soon(fastapi.concurrency.run_in_threadpool, acquire)

        await anyio.sleep(0.001)

        # The threadpool should now be full of threads waiting to acquire
        # The release function should be able to run without being blocked by acquires
        await fastapi_overflow.run_in_release_threadpool(release)

    assert len(acquired) == pool_size
