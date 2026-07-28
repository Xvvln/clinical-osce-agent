from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from contextvars import Context, ContextVar, Token, copy_context
from dataclasses import dataclass
from queue import Queue
from threading import BoundedSemaphore, Lock, Thread
from typing import Any, Generic, TypeVar


CallResultT = TypeVar("CallResultT")
DEFAULT_MODEL_CALL_MAX_CONCURRENCY = 8
DEFAULT_MODEL_CALL_TIMEOUT_SECONDS = 30.0
DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS = 1
MODEL_CALL_MAX_CONCURRENCY_ENV = "OSCE_MODEL_CALL_MAX_CONCURRENCY"
MODEL_CALL_TIMEOUT_SECONDS_ENV = "OSCE_MODEL_CALL_TIMEOUT_SECONDS"
MODEL_CALL_DEADLINE: ContextVar[float | None] = ContextVar(
    "model_call_deadline",
    default=None,
)


class ModelProviderPolicyError(Exception):
    pass


class ModelProviderOverloadedError(ModelProviderPolicyError):
    pass


class ModelProviderTimeoutError(ModelProviderPolicyError, TimeoutError):
    pass


@dataclass(frozen=True)
class _ModelCallJob(Generic[CallResultT]):
    future: Future[CallResultT]
    context: Context
    call: Callable[[], CallResultT]


class BoundedModelCallExecutor:
    """Run blocking providers on a small daemon pool with no admission queue."""

    def __init__(
        self,
        *,
        max_concurrency: int,
        thread_name_prefix: str = "osce-model-call",
    ) -> None:
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            raise ValueError("max_concurrency must be a positive integer")
        self.max_concurrency = max_concurrency
        self._slots = BoundedSemaphore(max_concurrency)
        self._jobs: Queue[_ModelCallJob[Any]] = Queue()
        for worker_index in range(max_concurrency):
            Thread(
                target=self._worker,
                name=f"{thread_name_prefix}-{worker_index + 1}",
                daemon=True,
            ).start()

    def submit(
        self,
        call: Callable[[], CallResultT],
    ) -> Future[CallResultT]:
        if not self._slots.acquire(blocking=False):
            raise ModelProviderOverloadedError(
                "model provider concurrency limit reached"
            )
        future: Future[CallResultT] = Future()
        try:
            self._jobs.put_nowait(
                _ModelCallJob(
                    future=future,
                    context=copy_context(),
                    call=call,
                )
            )
        except BaseException:
            self._slots.release()
            raise
        return future

    def run(
        self,
        call: Callable[[], CallResultT],
        *,
        timeout_seconds: float,
    ) -> CallResultT:
        normalized_timeout = _positive_finite_seconds(
            timeout_seconds,
            field_name="timeout_seconds",
        )
        future = self.submit(call)
        try:
            return future.result(timeout=normalized_timeout)
        except FutureTimeoutError as exc:
            # Running Python threads cannot be killed safely. Cancellation only
            # removes a job that has not started; otherwise its slot stays held
            # until the provider really returns, keeping leaked work bounded.
            future.cancel()
            raise ModelProviderTimeoutError(
                "model provider call exceeded its total time budget"
            ) from exc

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job.future.set_running_or_notify_cancel():
                    try:
                        result = job.context.run(job.call)
                    except BaseException as exc:
                        job.future.set_exception(exc)
                    else:
                        job.future.set_result(result)
            finally:
                self._slots.release()
                self._jobs.task_done()


class ModelRequestAdmissionGate:
    """A thread-safe counter used before sync endpoints consume worker threads."""

    def __init__(self, *, max_concurrency: int) -> None:
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            raise ValueError("max_concurrency must be a positive integer")
        self.max_concurrency = max_concurrency
        self._active = 0
        self._lock = Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self._active >= self.max_concurrency:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._active < 1:
                raise RuntimeError("model request admission released too often")
            self._active -= 1

    @property
    def active(self) -> int:
        with self._lock:
            return self._active


@contextmanager
def model_call_budget(
    timeout_seconds: float | None = None,
) -> Iterator[None]:
    timeout = _positive_finite_seconds(
        (
            MODEL_CALL_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        ),
        field_name="timeout_seconds",
    )
    requested_deadline = time.monotonic() + timeout
    current_deadline = MODEL_CALL_DEADLINE.get()
    deadline = (
        requested_deadline
        if current_deadline is None
        else min(current_deadline, requested_deadline)
    )
    token: Token[float | None] = MODEL_CALL_DEADLINE.set(deadline)
    try:
        yield
    finally:
        MODEL_CALL_DEADLINE.reset(token)


def run_model_provider_call(
    call: Callable[[], CallResultT],
    *,
    timeout_seconds: float | None = None,
    executor: BoundedModelCallExecutor | None = None,
) -> CallResultT:
    timeout = _remaining_model_call_seconds(
        MODEL_CALL_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    return (executor or model_call_executor).run(
        call,
        timeout_seconds=timeout,
    )


def set_model_call_deadline(
    timeout_seconds: float | None = None,
) -> Token[float | None]:
    timeout = _positive_finite_seconds(
        (
            MODEL_CALL_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        ),
        field_name="timeout_seconds",
    )
    requested_deadline = time.monotonic() + timeout
    current_deadline = MODEL_CALL_DEADLINE.get()
    return MODEL_CALL_DEADLINE.set(
        requested_deadline
        if current_deadline is None
        else min(current_deadline, requested_deadline)
    )


def reset_model_call_deadline(token: Token[float | None]) -> None:
    MODEL_CALL_DEADLINE.reset(token)


def _remaining_model_call_seconds(timeout_seconds: float) -> float:
    timeout = _positive_finite_seconds(
        timeout_seconds,
        field_name="timeout_seconds",
    )
    deadline = MODEL_CALL_DEADLINE.get()
    if deadline is None:
        return timeout
    remaining = min(timeout, deadline - time.monotonic())
    if remaining <= 0:
        raise ModelProviderTimeoutError(
            "model provider call exceeded its total time budget"
        )
    return remaining


def _positive_finite_seconds(
    value: float,
    *,
    field_name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a finite positive number")
    return float(value)


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return _positive_finite_seconds(
            float(raw_value),
            field_name=name,
        )
    except ValueError:
        return default


MODEL_CALL_MAX_CONCURRENCY = _positive_int_env(
    MODEL_CALL_MAX_CONCURRENCY_ENV,
    DEFAULT_MODEL_CALL_MAX_CONCURRENCY,
)
MODEL_CALL_TIMEOUT_SECONDS = _positive_float_env(
    MODEL_CALL_TIMEOUT_SECONDS_ENV,
    DEFAULT_MODEL_CALL_TIMEOUT_SECONDS,
)
model_call_executor = BoundedModelCallExecutor(
    max_concurrency=MODEL_CALL_MAX_CONCURRENCY,
)
model_request_admission_gate = ModelRequestAdmissionGate(
    max_concurrency=MODEL_CALL_MAX_CONCURRENCY,
)


__all__ = [
    "BoundedModelCallExecutor",
    "DEFAULT_MODEL_CALL_MAX_CONCURRENCY",
    "DEFAULT_MODEL_CALL_TIMEOUT_SECONDS",
    "DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS",
    "MODEL_CALL_MAX_CONCURRENCY",
    "MODEL_CALL_TIMEOUT_SECONDS",
    "ModelProviderOverloadedError",
    "ModelProviderPolicyError",
    "ModelProviderTimeoutError",
    "ModelRequestAdmissionGate",
    "model_call_budget",
    "model_request_admission_gate",
    "reset_model_call_deadline",
    "run_model_provider_call",
    "set_model_call_deadline",
]
