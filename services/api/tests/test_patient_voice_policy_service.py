from __future__ import annotations

from app.services.patient_voice_policy_service import build_patient_speech_profile


def test_patient_speech_profile_uses_young_male_voice_and_anxious_instructions() -> None:
    profile = build_patient_speech_profile(
        {
            "age_value": 22,
            "age_unit": "岁",
            "gender": "男",
            "occupation": "学生",
        },
        emotion="焦虑",
    )

    assert profile.voice == "Ethan"
    assert profile.model == "qwen3-tts-instruct-flash"
    assert profile.optimize_instructions is True
    assert profile.normalized_gender == "male"
    assert profile.age_band == "young_adult"
    assert profile.normalized_emotion == "anxious"
    assert "年轻男性患者" in profile.instructions
    assert "学生" in profile.instructions
    assert "焦虑" in profile.instructions or "紧张" in profile.instructions
    assert "不要播报舞台说明" in profile.instructions
