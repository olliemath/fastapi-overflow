# Most of this file is vendored from the test suite in this fastapi PR:
# https://github.com/fastapi/fastapi/pull/12066/commits
# Copyright (c) 2024 Noah Klein
# Licensed under the MIT License
import threading
import time
from collections.abc import Iterator

import pytest
from anyio import CapacityLimiter
from fastapi import Depends, FastAPI
from pydantic import BaseModel

import fastapi_overflow


@pytest.fixture
def patched_app() -> FastAPI:
    app = FastAPI()
    fastapi_overflow.patch()

    class Item(BaseModel):
        name: str
        id: int

    # Mutex, acting as our "connection pool" for a database for example
    mutex_pool = threading.Lock()

    # Simulate releasing a pooled resource in the teardown of a Depends,
    # which in reality is usually a database connection or similar.
    def release_resource() -> Iterator[None]:
        try:
            time.sleep(0.001)
            yield
        finally:
            time.sleep(0.001)
            mutex_pool.release()

    # An endpoint that uses Depends for resource management and also includes
    # a response_model definition would previously deadlock in the validation
    # of the model and the cleanup of the Depends
    @app.get("/deadlock", response_model=Item)
    def get_deadlock(dep: None = Depends(release_resource)):
        mutex_pool.acquire()
        return Item(name="foo", id=1)

    return app


@pytest.fixture
def release_capacity_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the release capacity limiter before/after tests to avoid interference
    between different anyio backends."""
    monkeypatch.setattr(
        fastapi_overflow, "_release_capacity_limiter", CapacityLimiter(5)
    )
