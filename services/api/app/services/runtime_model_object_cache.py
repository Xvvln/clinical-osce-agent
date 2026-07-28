from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

from app.services.runtime_model_config_store import runtime_model_config_store


RuntimeObjectT = TypeVar("RuntimeObjectT")


class RuntimeModelObjectCache(Generic[RuntimeObjectT]):
    """Bounded cache that returns a request-local object for one config snapshot."""

    def __init__(self, *, max_entries: int = 16) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._lock = Lock()
        self._objects: OrderedDict[tuple[str, ...], RuntimeObjectT] = OrderedDict()

    def get_or_create(self, factory: Callable[[], RuntimeObjectT]) -> RuntimeObjectT:
        runtime_config = runtime_model_config_store.get_active_config()
        cache_key = (
            ("env",)
            if runtime_config is None
            else ("runtime", *runtime_config.cache_key())
        )
        with self._lock:
            if cache_key in self._objects:
                cached_object = self._objects.pop(cache_key)
                self._objects[cache_key] = cached_object
                return cached_object

            # Build under the cache lock so first-use concurrency for one key cannot
            # create an extra provider client that has no reliable close contract.
            # The immutable request snapshot stays pinned throughout construction.
            with runtime_model_config_store.use_config(runtime_config):
                created_object = factory()
            self._objects[cache_key] = created_object
            while len(self._objects) > self._max_entries:
                self._objects.popitem(last=False)
            return created_object


__all__ = ["RuntimeModelObjectCache"]
