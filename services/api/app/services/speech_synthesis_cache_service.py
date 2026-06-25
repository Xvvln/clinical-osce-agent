from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.dashscope_speech_service import SpeechSynthesisResult

SPEECH_SYNTHESIS_CACHE_POLICY_VERSION = "patient_tts_cache_v1"
DEFAULT_SPEECH_SYNTHESIS_CACHE_TTL_SECONDS = 30 * 60
DEFAULT_SPEECH_SYNTHESIS_CACHE_MAX_ENTRIES = 128
DEFAULT_SPEECH_SYNTHESIS_CACHE_MAX_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class _SpeechSynthesisCacheEntry:
    result: SpeechSynthesisResult
    created_at: float
    expires_at: float
    size_bytes: int


class SpeechSynthesisCache:
    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_SPEECH_SYNTHESIS_CACHE_TTL_SECONDS,
        max_entries: int = DEFAULT_SPEECH_SYNTHESIS_CACHE_MAX_ENTRIES,
        max_bytes: int = DEFAULT_SPEECH_SYNTHESIS_CACHE_MAX_BYTES,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._max_entries = max(1, int(max_entries))
        self._max_bytes = max(1, int(max_bytes))
        self._now = now
        self._entries: OrderedDict[str, _SpeechSynthesisCacheEntry] = OrderedDict()
        self._total_bytes = 0

    def build_key(
        self,
        *,
        session_id: str,
        message_index: int,
        text: str,
        model: str | None,
        voice: str | None,
        instructions: str | None,
        optimize_instructions: bool | None,
        emotion: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "policy_version": SPEECH_SYNTHESIS_CACHE_POLICY_VERSION,
            "session_id": session_id,
            "message_index": message_index,
            "text": text,
            "model": model or "",
            "voice": voice or "",
            "instructions": instructions or "",
            "optimize_instructions": optimize_instructions,
            "emotion": emotion or "",
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, key: str) -> SpeechSynthesisResult | None:
        self._prune_expired()
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._now():
            self._remove(key)
            return None
        self._entries.move_to_end(key)
        return entry.result

    def set(self, key: str, result: SpeechSynthesisResult) -> None:
        self._prune_expired()
        size_bytes = len(result.audio_bytes)
        if size_bytes > self._max_bytes:
            return
        self._remove(key)
        now = self._now()
        self._entries[key] = _SpeechSynthesisCacheEntry(
            result=result,
            created_at=now,
            expires_at=now + self._ttl_seconds,
            size_bytes=size_bytes,
        )
        self._total_bytes += size_bytes
        self._evict_until_within_limits()

    def clear(self) -> None:
        self._entries.clear()
        self._total_bytes = 0

    def _prune_expired(self) -> None:
        now = self._now()
        expired_keys = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired_keys:
            self._remove(key)

    def _evict_until_within_limits(self) -> None:
        while len(self._entries) > self._max_entries or self._total_bytes > self._max_bytes:
            oldest_key = next(iter(self._entries), "")
            if not oldest_key:
                break
            self._remove(oldest_key)

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes = max(0, self._total_bytes - entry.size_bytes)


speech_synthesis_cache = SpeechSynthesisCache()


__all__ = ["SpeechSynthesisCache", "speech_synthesis_cache"]
