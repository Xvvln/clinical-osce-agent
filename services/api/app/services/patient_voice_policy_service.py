from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_PATIENT_TTS_INSTRUCT_MODEL = "qwen3-tts-instruct-flash"
DEFAULT_MALE_PATIENT_TTS_VOICE = "Ethan"
DEFAULT_FEMALE_PATIENT_TTS_VOICE = "Serena"
DEFAULT_UNKNOWN_PATIENT_TTS_VOICE = "Serena"


@dataclass(frozen=True)
class PatientSpeechProfile:
    model: str
    voice: str
    instructions: str
    optimize_instructions: bool
    normalized_gender: str
    age_band: str
    normalized_emotion: str
    policy: str = "patient_context"


def build_patient_speech_profile(patient_profile: Mapping[str, Any] | object, *, emotion: str | None = None) -> PatientSpeechProfile:
    gender = _normalize_gender(_field(patient_profile, "gender"))
    age = _patient_age(patient_profile)
    age_band = _age_band(age)
    normalized_emotion = _normalize_emotion(emotion)
    voice = _voice_for(gender)
    model = _env("OSCE_DASHSCOPE_TTS_INSTRUCT_MODEL", DEFAULT_PATIENT_TTS_INSTRUCT_MODEL)
    occupation = str(_field(patient_profile, "occupation") or "").strip()

    instructions = _build_instructions(
        gender=gender,
        age_band=age_band,
        occupation=occupation,
        emotion=normalized_emotion,
    )
    return PatientSpeechProfile(
        model=model,
        voice=voice,
        instructions=instructions,
        optimize_instructions=True,
        normalized_gender=gender,
        age_band=age_band,
        normalized_emotion=normalized_emotion,
    )


def _field(source: Mapping[str, Any] | object, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _patient_age(patient_profile: Mapping[str, Any] | object) -> int | None:
    raw_age = _field(patient_profile, "age_value")
    if isinstance(raw_age, int):
        return raw_age
    if isinstance(raw_age, float):
        return int(raw_age)
    if isinstance(raw_age, str):
        match = re.search(r"\d+", raw_age)
        if match:
            return int(match.group(0))
    raw_age_label = _field(patient_profile, "age")
    if isinstance(raw_age_label, str):
        match = re.search(r"\d+", raw_age_label)
        if match:
            return int(match.group(0))
    return None


def _normalize_gender(value: Any) -> str:
    gender = str(value or "").strip().lower()
    if gender in {"男", "男性", "male", "man", "m"}:
        return "male"
    if gender in {"女", "女性", "female", "woman", "f"}:
        return "female"
    return "unknown"


def _age_band(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age < 18:
        return "adolescent"
    if age <= 35:
        return "young_adult"
    if age < 60:
        return "middle_aged"
    return "older_adult"


def _normalize_emotion(value: str | None) -> str:
    emotion = str(value or "").strip().lower()
    if not emotion:
        return "neutral"
    if any(token in emotion for token in ("焦虑", "紧张", "担忧", "担心", "害怕", "恐惧", "anxious", "worried", "fear")):
        return "anxious"
    if any(token in emotion for token in ("疼", "痛", "难受", "不舒服", "pain")):
        return "pain"
    if any(token in emotion for token in ("困惑", "疑惑", "不明白", "confused")):
        return "confused"
    if any(token in emotion for token in ("生气", "不满", "烦躁", "frustrated", "angry")):
        return "frustrated"
    if any(token in emotion for token in ("缓解", "放心", "放松", "relieved")):
        return "relieved"
    return "neutral"


def _voice_for(gender: str) -> str:
    if gender == "male":
        return _env("OSCE_DASHSCOPE_TTS_VOICE_MALE", DEFAULT_MALE_PATIENT_TTS_VOICE)
    if gender == "female":
        return _env("OSCE_DASHSCOPE_TTS_VOICE_FEMALE", DEFAULT_FEMALE_PATIENT_TTS_VOICE)
    return _env("OSCE_DASHSCOPE_TTS_VOICE_PATIENT_DEFAULT", DEFAULT_UNKNOWN_PATIENT_TTS_VOICE)


def _build_instructions(*, gender: str, age_band: str, occupation: str, emotion: str) -> str:
    identity = _identity_label(gender=gender, age_band=age_band)
    occupation_clause = f"，职业是{occupation}" if occupation else ""
    emotion_clause = _emotion_instruction(emotion)
    return (
        f"{identity}{occupation_clause}。"
        "你是 OSCE 标准化病人，只用第一人称说患者本人会说的话。"
        "声音要自然口语化，符合年龄和身份，保持临床训练真实克制。"
        f"{emotion_clause}"
        "不要播报舞台说明、括号动作、旁白、医生建议或隐藏病例信息。"
    )


def _identity_label(*, gender: str, age_band: str) -> str:
    age_label = {
        "adolescent": "青少年",
        "young_adult": "年轻",
        "middle_aged": "中年",
        "older_adult": "老年",
        "unknown": "",
    }[age_band]
    gender_label = {"male": "男性", "female": "女性", "unknown": ""}[gender]
    if age_label or gender_label:
        return f"{age_label}{gender_label}患者"
    return "患者"


def _emotion_instruction(emotion: str) -> str:
    instructions = {
        "anxious": "当前情绪是焦虑；语气带担忧和紧张，语速略快，句子可以稍短，但不要夸张。",
        "pain": "当前情绪是疼痛不适；语气带痛苦和停顿，短句表达，但不要夸张呻吟。",
        "confused": "当前情绪是困惑；语气稍迟疑，带一点不确定感。",
        "frustrated": "当前情绪是烦躁或不满；语气略急，但仍像真实患者交流。",
        "relieved": "当前情绪有所缓解；语气比前一轮更放松。",
        "neutral": "当前情绪平稳；语气自然清楚。",
    }
    return instructions.get(emotion, instructions["neutral"])


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


__all__ = ["PatientSpeechProfile", "build_patient_speech_profile"]
