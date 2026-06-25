from __future__ import annotations

from app.services.dashscope_speech_service import SpeechSynthesisResult
from app.services.speech_synthesis_cache_service import SpeechSynthesisCache


def test_speech_synthesis_cache_reuses_entries_until_ttl_expires() -> None:
    now = 1_000.0
    cache = SpeechSynthesisCache(ttl_seconds=30, max_entries=4, now=lambda: now)
    result = SpeechSynthesisResult(
        audio_bytes=b"audio",
        mime_type="audio/wav",
        provider="dashscope",
        model="qwen3-tts-instruct-flash",
        voice="Ethan",
        request_id="request-1",
    )
    cache_key = cache.build_key(
        session_id="session-1",
        message_index=0,
        text="患者回复",
        model="qwen3-tts-instruct-flash",
        voice="Ethan",
        instructions="年轻男性患者，语气焦虑。",
        optimize_instructions=True,
        emotion="anxious",
    )

    cache.set(cache_key, result)

    assert cache.get(cache_key) == result
    now = 1_031.0
    assert cache.get(cache_key) is None


def test_speech_synthesis_cache_key_changes_when_message_context_changes() -> None:
    cache = SpeechSynthesisCache(ttl_seconds=30, max_entries=4, now=lambda: 1_000.0)

    base_key = cache.build_key(
        session_id="session-1",
        message_index=0,
        text="患者回复",
        model="qwen3-tts-instruct-flash",
        voice="Ethan",
        instructions="年轻男性患者，语气焦虑。",
        optimize_instructions=True,
        emotion="anxious",
    )
    changed_emotion_key = cache.build_key(
        session_id="session-1",
        message_index=0,
        text="患者回复",
        model="qwen3-tts-instruct-flash",
        voice="Ethan",
        instructions="年轻男性患者，语气平静。",
        optimize_instructions=True,
        emotion="neutral",
    )
    changed_message_key = cache.build_key(
        session_id="session-1",
        message_index=1,
        text="患者回复",
        model="qwen3-tts-instruct-flash",
        voice="Ethan",
        instructions="年轻男性患者，语气焦虑。",
        optimize_instructions=True,
        emotion="anxious",
    )

    assert base_key != changed_emotion_key
    assert base_key != changed_message_key
    assert "患者回复" not in base_key


def test_speech_synthesis_cache_evicts_oldest_entry_when_capacity_is_exceeded() -> None:
    now = 1_000.0
    cache = SpeechSynthesisCache(ttl_seconds=60, max_entries=1, now=lambda: now)
    first = SpeechSynthesisResult(
        audio_bytes=b"first",
        mime_type="audio/wav",
        provider="dashscope",
        model="model",
        voice="voice",
        request_id="first",
    )
    second = SpeechSynthesisResult(
        audio_bytes=b"second",
        mime_type="audio/wav",
        provider="dashscope",
        model="model",
        voice="voice",
        request_id="second",
    )
    first_key = cache.build_key(
        session_id="session-1",
        message_index=0,
        text="第一条",
        model="model",
        voice="voice",
        instructions="",
        optimize_instructions=None,
        emotion="",
    )
    second_key = cache.build_key(
        session_id="session-1",
        message_index=1,
        text="第二条",
        model="model",
        voice="voice",
        instructions="",
        optimize_instructions=None,
        emotion="",
    )

    cache.set(first_key, first)
    now = 1_001.0
    cache.set(second_key, second)

    assert cache.get(first_key) is None
    assert cache.get(second_key) == second
