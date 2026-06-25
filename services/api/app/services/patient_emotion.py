from __future__ import annotations

from typing import Any


def normalize_patient_emotion(value: Any) -> str:
    emotion = str(value or "").strip()
    if not emotion or emotion.lower() in {"neutral", "none"} or emotion in {"平静", "正常"}:
        return ""
    aliases = {
        "worry": "担忧",
        "worried": "担忧",
        "anxiety": "焦虑",
        "anxious": "焦虑",
        "fear": "担忧",
        "fearful": "担忧",
        "pain": "痛苦",
        "painful": "痛苦",
        "relieved": "欣慰",
    }
    return aliases.get(emotion.lower(), emotion)


def infer_patient_emotion(reply: str) -> str:
    emotion_rules = [
        ("担忧", ("担心", "担忧", "害怕", "怕", "恐惧", "忧虑", "顾虑", "不放心")),
        ("焦虑", ("焦虑", "紧张", "不安", "慌")),
        ("痛苦", ("痛苦", "难受", "煎熬", "折磨")),
        ("困惑", ("不明白", "不理解", "听不懂", "困惑")),
        ("欣慰", ("谢谢", "感谢", "放心", "安心", "好多了")),
    ]
    for emotion, keywords in emotion_rules:
        if any(keyword in reply for keyword in keywords):
            return emotion
    return ""
