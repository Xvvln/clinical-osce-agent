from __future__ import annotations

import json
import os
import re
import threading
import time
from contextvars import ContextVar, Token
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.services.model_call_policy import run_model_provider_call

CallResultT = TypeVar("CallResultT")
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_API_CALL_LOG_PATH = PROJECT_ROOT / "data" / "runtime" / "model_api_calls.jsonl"
MAX_ERROR_MESSAGE_LENGTH = 220
MAX_LOG_ENTRIES_READ = 2000
DEFAULT_API_CALL_LOG_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_API_CALL_LOG_BACKUP_COUNT = 3
API_CALL_CONTEXT: ContextVar[dict[str, str]] = ContextVar("api_call_context", default={})
SECRET_PATTERNS = [
    re.compile(r"(?i)((?:x-goog-api-key|api[_-]?key|key)\s*[=:]\s*)[\"']?[^\s,;&#\"']+"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"sk-[A-Za-z0-9._\-]+"),
    re.compile(r"tp-[A-Za-z0-9._\-]+"),
]
URL_PATTERN = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>'\"]+")


class ApiCallLogStore:
    def __init__(
        self,
        path: Path = DEFAULT_API_CALL_LOG_PATH,
        *,
        max_bytes: int = DEFAULT_API_CALL_LOG_MAX_BYTES,
        backup_count: int = DEFAULT_API_CALL_LOG_BACKUP_COUNT,
    ) -> None:
        self._path = path
        self._max_bytes = max(1, int(max_bytes))
        self._backup_count = max(1, int(backup_count))
        self._lock = threading.Lock()

    def record(
        self,
        *,
        provider: str,
        operation: str,
        model: str,
        endpoint: str,
        success: bool,
        duration_ms: float,
        status_code: int | None = None,
        error: BaseException | None = None,
    ) -> None:
        context = API_CALL_CONTEXT.get()
        entry = {
            "created_at": datetime.now(UTC).isoformat(),
            "provider": provider,
            "operation": operation,
            "model": model,
            "endpoint": _safe_endpoint(endpoint),
            "caller": context.get("caller", ""),
            "user_id": context.get("user_id", ""),
            "student_id": context.get("student_id", ""),
            "session_id": context.get("session_id", ""),
            "success": bool(success),
            "status_code": status_code if status_code is not None else _status_code_from_error(error),
            "duration_ms": round(max(duration_ms, 0.0), 1),
            "error_type": error.__class__.__name__ if error is not None else "",
            "error_message": _sanitize_error_message(str(error)) if error is not None else "",
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serialized_entry = (
                json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            serialized_size = len(serialized_entry.encode("utf-8"))
            with self._lock:
                self._rotate_if_needed(serialized_size)
                with self._path.open("a", encoding="utf-8") as file:
                    file.write(serialized_entry)
                os.chmod(self._path, 0o600)
        except OSError:
            return

    def build_admin_payload(self, *, limit: int = 80) -> dict[str, Any]:
        entries = self._read_entries()
        recent_entries = list(reversed(entries))[: max(1, min(limit, 200))]
        return {
            "summary": _build_summary(entries),
            "summary_by_provider": _build_provider_summaries(entries),
            "logs": recent_entries,
        }

    def _read_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_entries_unlocked()

    def _read_entries_unlocked(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in self._ordered_log_paths():
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    entries.append(parsed)
            if len(entries) > MAX_LOG_ENTRIES_READ:
                entries = entries[-MAX_LOG_ENTRIES_READ:]
        return entries[-MAX_LOG_ENTRIES_READ:]

    def _rotate_if_needed(self, incoming_size: int) -> None:
        if not self._path.exists():
            return
        try:
            current_size = self._path.stat().st_size
        except OSError:
            return
        if current_size + incoming_size <= self._max_bytes:
            return

        for index in range(self._backup_count, 0, -1):
            destination = self._backup_path(index)
            source = (
                self._path
                if index == 1
                else self._backup_path(index - 1)
            )
            if destination.exists():
                destination.unlink()
            if source.exists():
                source.replace(destination)

    def _ordered_log_paths(self) -> list[Path]:
        return [
            *[
                self._backup_path(index)
                for index in range(self._backup_count, 0, -1)
            ],
            self._path,
        ]

    def _backup_path(self, index: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{index}")


def _build_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    total_calls = len(entries)
    success_calls = sum(1 for entry in entries if entry.get("success") is True)
    failed_calls = total_calls - success_calls
    durations = [float(entry.get("duration_ms", 0.0)) for entry in entries if isinstance(entry.get("duration_ms"), int | float)]
    return {
        "total_calls": total_calls,
        "success_calls": success_calls,
        "failed_calls": failed_calls,
        "success_rate": (success_calls / total_calls) if total_calls else 0.0,
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
    }


def _build_provider_summaries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        grouped[str(entry.get("provider") or "unknown")].append(entry)
    summaries = [
        {"provider": provider, **_build_summary(provider_entries)}
        for provider, provider_entries in grouped.items()
    ]
    return sorted(summaries, key=lambda item: (-int(item["total_calls"]), str(item["provider"])))


def _safe_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    if not normalized:
        return ""
    if "://" not in normalized:
        return normalized.split("?")[0]
    parsed = urlsplit(normalized)
    # urlsplit().netloc retains username/password. Keep only the host/port
    # segment so diagnostics cannot persist credentials embedded in a URL.
    safe_netloc = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, safe_netloc, parsed.path, "", ""))


def _status_code_from_error(error: BaseException | None) -> int | None:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    candidates = [
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ]
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool) and 100 <= candidate <= 599:
            return candidate
    return None


def _sanitize_error_message(message: str) -> str:
    sanitized = URL_PATTERN.sub(lambda match: _safe_endpoint(match.group(0)), message)
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1) if match.groups() else ''}[redacted]", sanitized)
    sanitized = sanitized.replace("\n", " ").replace("\r", " ").strip()
    if len(sanitized) > MAX_ERROR_MESSAGE_LENGTH:
        sanitized = f"{sanitized[:MAX_ERROR_MESSAGE_LENGTH - 3]}..."
    return sanitized


api_call_log_store = ApiCallLogStore()


def set_api_call_context(*, user_id: str = "", caller: str = "", student_id: str = "", session_id: str = "") -> Token[dict[str, str]]:
    return API_CALL_CONTEXT.set(
        {
            "caller": caller.strip(),
            "user_id": user_id.strip(),
            "student_id": student_id.strip(),
            "session_id": session_id.strip(),
        }
    )


def reset_api_call_context(token: Token[dict[str, str]]) -> None:
    API_CALL_CONTEXT.reset(token)


def call_with_api_logging(
    *,
    provider: str,
    operation: str,
    model: str,
    endpoint: str,
    call: Callable[[], CallResultT],
    timeout_seconds: float | None = None,
) -> CallResultT:
    started_at = time.perf_counter()
    try:
        result = run_model_provider_call(
            call,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        api_call_log_store.record(
            provider=provider,
            operation=operation,
            model=model,
            endpoint=endpoint,
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            error=exc,
        )
        raise
    status_code = getattr(result, "status_code", None)
    api_call_log_store.record(
        provider=provider,
        operation=operation,
        model=model,
        endpoint=endpoint,
        success=True,
        duration_ms=(time.perf_counter() - started_at) * 1000,
        status_code=status_code if isinstance(status_code, int) else None,
    )
    return result


__all__ = ["ApiCallLogStore", "api_call_log_store", "call_with_api_logging", "reset_api_call_context", "set_api_call_context"]
