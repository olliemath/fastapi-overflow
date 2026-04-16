# FastAPI Overflow

When using FastAPI with a synchronous SQLAlchemy session dependency,
as per the official example <...>, high loads can lead to temporary
deadlocks, timeouts and poor performance.

This is a known issue, for which a PR is open. This library exists to allow users
to easily patch the issue and run their code in the mean time.

We provide 3 primary functions:

- `fastapi_overflow.patch` which should be called before starting your app in order to patch FastAPI's thread handling
- `fastapi_overflow.run_in_threadpool` which should be used instead of `starlette.concurrency.run_in_threadpool` or `fastapi.concurrency.run_in_threadpool`
- `fastapi_overflow.iterate_in_threadpool` which should be used instead of `starlette.concurrency.iterate_in_threadpool` or `fastapi.concurrency.iterate_in_threadpool`

## Usage

Use it like this:

```python
from fastapi import FastAPI
from fastapi_overflow import patch

patch()  # run this before starting your app
app = FastAPI()
```
