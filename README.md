# FastAPI Overflow

When using FastAPI with a synchronous SQLAlchemy session dependency,
per the official example https://fastapi.tiangolo.com/tutorial/sql-databases/,
high loads can lead to temporary deadlocks, timeouts and poor performance.

This is a known issue, for which a [PR is open](https://github.com/fastapi/fastapi/pull/12066). This library exists to allow users
to easily patch the issue and run their code in the mean time.

We provide a single function to patch fastapi: `fastapi_overflow.patch()` should be called before starting your app in order to patch FastAPI's thread handling.

## Usage

Use it like this:

```python
from fastapi import FastAPI
from fastapi_overflow import patch

patch()  # run this before starting your app
app = FastAPI()
```

## Changing the default thread limit

You can increase the number of threads from the default (40) using the `fastapi_overflow.set_thread_limit` function.
With a very high number of threads you might also want to increase the reserve used to prevent deadlocks from its
default of 5. You will need to add this to your startup events, or lifetime function:

```python
@app.on_event("startup")
def on_startup():
    fastapi_overflow.set_thread_limit(default_limit=80, reserve_limit=10)
    ...  # any other setup here
```

Some experimentation is needed to find the best numbers for your workload.
