from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx

CallResultT = TypeVar("CallResultT")
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_API_CALL_LOG_PATH = PROJECT_ROOT / "data" / "runtime" / "model_api_calls.jsonl"
MAX_ERROR_MESSAGE_LENGTH = 220
MAX_LOG_ENTRIES_READ = 2000
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"sk-[A-Za-z0-9._\-]+"),
    re.compile(r"tp-[A-Za-z0-9._\-]+"),
]


class ApiCallLogStore:
    def __init__(self, path: Path = DEFAULT_API_CALL_LOG_PATH) -> None:
        self._path = path
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
        entry = {
            "created_at": datetime.now(UTC).isoformat(),
            "provider": provider,
            "operation": operation,
            "model": model,
            "endpoint": _safe_endpoint(endpoint),
            "success": bool(success),
            "status_code": status_code if status_code is not None else _status_code_from_error(error),
            "duration_ms": round(max(duration_ms, 0.0), 1),
            "error_type": error.__class__.__name__ if error is not None else "",
            "error_message": _sanitize_error_message(str(error)) if error is not None else "",
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
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
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries: list[dict[str, Any]] = []
        for line in lines[-MAX_LOG_ENTRIES_READ:]:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries


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
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _status_code_from_error(error: BaseException | None) -> int | None:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    return None


def _sanitize_error_message(message: str) -> str:
    sanitized = message
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1) if match.groups() else ''}[redacted]", sanitized)
    sanitized = sanitized.replace("\n", " ").replace("\r", " ").strip()
    if len(sanitized) > MAX_ERROR_MESSAGE_LENGTH:
        sanitized = f"{sanitized[:MAX_ERROR_MESSAGE_LENGTH - 3]}..."
    return sanitized


api_call_log_store = ApiCallLogStore()


def call_with_api_logging(
    *,
    provider: str,
    operation: str,
    model: str,
    endpoint: str,
    call: Callable[[], CallResultT],
) -> CallResultT:
    started_at = time.perf_counter()
    try:
        result = call()
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


__all__ = ["ApiCallLogStore", "api_call_log_store", "call_with_api_logging"]
