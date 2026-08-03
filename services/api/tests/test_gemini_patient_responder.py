import json
import os

import pytest

from app.services import gemini_patient_responder as module
from app.services import anthropic_chat_client as anthropic_module
from app.services import openai_compatible_chat_client as openai_module
from app.services.runtime_model_config_store import runtime_model_config_store


class FakeModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        raise AssertionError("本测试只验证客户端创建，不应触发模型调用")


class FakeVertexClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.models = FakeModels()


def test_gemini_patient_settings_defaults_to_gemini_31_pro_preview() -> None:
    settings = module.GeminiPatientSettings(_env_file=None)

    assert settings.location == "global"
    assert settings.model == "gemini-3.1-pro-preview"
    assert settings.proxy_url == "http://127.0.0.1:7897"


def test_patient_responder_prompt_requires_real_patient_voice() -> None:
    assert "像真实来就诊的患者" in module.SYSTEM_PROMPT_TEMPLATE
    assert "不要像病历摘要" in module.SYSTEM_PROMPT_TEMPLATE
    assert "把医学化表达改成生活化表达" in module.SYSTEM_PROMPT_TEMPLATE
    assert "转移性右下腹痛" in module.SYSTEM_PROMPT_TEMPLATE
    assert "肚子疼，后来右下腹更明显" in module.SYSTEM_PROMPT_TEMPLATE
    assert "低热" in module.SYSTEM_PROMPT_TEMPLATE
    assert "有点发热" in module.SYSTEM_PROMPT_TEMPLATE
    assert "不要主动引导学生下一步该问什么" in module.SYSTEM_PROMPT_TEMPLATE
    assert "patient_private_context" not in module.SYSTEM_PROMPT_TEMPLATE
    assert "answerable_fact_candidates" in module.SYSTEM_PROMPT_TEMPLATE
    assert "revealed_fact_ids" not in module.SYSTEM_PROMPT_TEMPLATE
    assert "本轮临时令牌" in module.SYSTEM_PROMPT_TEMPLATE
    assert "dialogue_context" in module.SYSTEM_PROMPT_TEMPLATE
    assert "is_repeated_fact_question" not in module.SYSTEM_PROMPT_TEMPLATE
    assert "repeated_fact_ids" not in module.SYSTEM_PROMPT_TEMPLATE
    assert "fact_ids_used" in module.SYSTEM_PROMPT_TEMPLATE
    assert "必须逐一覆盖所有 answerable_fact_candidates" in module.SYSTEM_PROMPT_TEMPLATE
    assert "emotion" in module.SYSTEM_PROMPT_TEMPLATE
    assert "患者当前可见情绪" in module.SYSTEM_PROMPT_TEMPLATE
    assert "patient_affect_state" in module.SYSTEM_PROMPT_TEMPLATE
    assert "只能影响语气" in module.SYSTEM_PROMPT_TEMPLATE
    assert "不能新增病例事实" in module.SYSTEM_PROMPT_TEMPLATE
    assert "role_skill_policy" in module.SYSTEM_PROMPT_TEMPLATE
    assert "不能选择、补写或改变任何病例事实" in module.SYSTEM_PROMPT_TEMPLATE


def test_create_configured_patient_responder_falls_back_to_deterministic_without_external_config(monkeypatch) -> None:
    runtime_model_config_store.clear()
    for key in [
        "OSCE_GEMINI_PATIENT_API_KEY",
        "OSCE_GEMINI_PATIENT_PROJECT",
        "OSCE_VERTEX_API_KEY",
        "OSCE_VERTEX_PROJECT",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OSCE_OPENAI_API_KEY",
        "OSCE_OPENAI_MODEL",
    ]:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "false")

    def fail_client(**kwargs: object) -> object:
        raise AssertionError(f"external Gemini client should not be created: {kwargs}")

    monkeypatch.setattr(module.genai, "Client", fail_client)

    responder = module._create_configured_responder()
    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="哪里疼？",
            current_intents=["ask_location"],
            canonical_answer="右下腹疼痛明显。",
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert isinstance(responder, module.DeterministicPatientResponder)
    assert reply.reply == "右下腹疼痛明显。"


def test_deterministic_patient_responder_keeps_context_without_repeat_branching() -> None:
    responder = module.DeterministicPatientResponder()

    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="有对什么过敏吗？",
            current_intents=["ask_allergy"],
            canonical_answer="没有药物过敏，吃东西也没发现过敏。",
            revealed_fact_id="appendicitis_001.hf_07",
            revealed_fact_ids=["appendicitis_001.hf_07"],
            dialogue_context={
                "recent_messages": [
                    {"role": "student", "content": "有对什么过敏吗？"},
                    {"role": "patient", "content": "没有药物过敏，吃东西也没发现过敏。"},
                ],
            },
            answerable_fact_candidates=[
                {
                    "fact_id": "appendicitis_001.hf_07",
                    "canonical_answer": "没有药物过敏，吃东西也没发现过敏。",
                }
            ],
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert reply.reply == "没有药物过敏，吃东西也没发现过敏。"


def test_deterministic_patient_responder_infers_visible_emotion() -> None:
    responder = module.DeterministicPatientResponder()

    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="你现在最担心什么？",
            current_intents=["ask_ideas_concerns_expectations"],
            canonical_answer="我有点害怕是不是很严重。",
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert reply.reply == "我有点害怕是不是很严重。"
    assert reply.emotion == "担忧"


class FakePatientFactIdClient:
    def __init__(self, response: module.PatientResponderResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, object],
        response_model: object,
        temperature: float | None = None,
    ) -> module.PatientResponderResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "payload": payload,
                "response_model": response_model,
                "temperature": temperature,
            }
        )
        return self.response


def test_patient_responder_rejects_unapproved_fact_ids_from_model() -> None:
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(reply="我昨天开始疼的。", fact_ids_used=["appendicitis_001.hf_02"])
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )

    request = module.PatientResponderRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        student_message="什么时候开始疼？",
        current_intents=["ask_onset"],
        canonical_answer="24 小时前开始，最初是上腹部隐痛。",
        revealed_fact_id="appendicitis_001.hf_01",
        answerable_fact_candidates=[
            {
                "fact_id": "appendicitis_001.hf_01",
                "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
            }
        ],
        forbidden_terms=["急性阑尾炎"],
        forbidden_context={"diagnosis_terms": ["急性阑尾炎"]},
    )

    with pytest.raises(RuntimeError, match="未授权病例事实"):
        responder(request)


def test_patient_responder_rejects_partial_fact_coverage_for_multi_intent_question() -> None:
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(
            reply="今天上午活动完之后开始胸口疼，到现在大概两个小时了。",
            fact_ids_used=["fact_1"],
        )
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )

    request = module.PatientResponderRequest(
        case_id="acs_001",
        case_title="胸痛伴出汗教学病例",
        chief_complaint="胸骨后压榨性胸痛 2 小时，伴大汗。",
        student_message="胸痛什么时候开始的？在哪里痛？什么性质？有没有出汗、气短或放射痛？",
        current_intents=["ask_onset", "ask_location", "ask_character", "ask_migration"],
        canonical_answer=(
            "今天上午活动后开始胸口痛，到现在 2 个小时了。；"
            "胸口像被压着一样闷痛，不是针扎样疼。；"
            "疼痛会往左肩和左上臂放射。"
        ),
        revealed_fact_id="acs_001.hf_01",
        answerable_fact_candidates=[
            {
                "fact_id": "acs_001.hf_01",
                "canonical_answer": "今天上午活动后开始胸口痛，到现在 2 个小时了。",
            },
            {
                "fact_id": "acs_001.hf_02",
                "canonical_answer": "胸口像被压着一样闷痛，不是针扎样疼。",
            },
            {
                "fact_id": "acs_001.hf_03",
                "canonical_answer": "疼痛会往左肩和左上臂放射。",
            },
        ],
        forbidden_terms=["急性心肌梗死", "急性冠脉综合征"],
    )

    with pytest.raises(RuntimeError, match="未覆盖本轮多个问诊事实"):
        responder(request)


def test_lazy_patient_responder_uses_canonical_answer_when_model_output_fails_fact_gate(monkeypatch) -> None:
    class UnsafeModelResponder:
        def __call__(self, request: module.PatientResponderRequest) -> str:
            raise RuntimeError("标准化病人回答声明使用了未授权病例事实：['appendicitis_001.hf_99']")

    monkeypatch.setattr(module, "_create_configured_responder", lambda: UnsafeModelResponder())

    responder = module.LazyGeminiPatientResponder()
    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="什么时候开始疼？",
            current_intents=["ask_onset"],
            canonical_answer="24 小时前开始，最初是上腹部隐痛。",
            revealed_fact_id="appendicitis_001.hf_01",
            answerable_fact_candidates=[
                {
                    "fact_id": "appendicitis_001.hf_01",
                    "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
                }
            ],
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert reply.reply == "24 小时前开始，最初是上腹部隐痛。"


def test_patient_responder_accepts_declared_answerable_fact_ids() -> None:
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(reply="我昨天开始疼的。", fact_ids_used=["fact_1"])
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )

    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="什么时候开始疼？",
            current_intents=["ask_onset"],
            canonical_answer="24 小时前开始，最初是上腹部隐痛。",
            revealed_fact_id="appendicitis_001.hf_01",
            answerable_fact_candidates=[
                {
                    "fact_id": "appendicitis_001.hf_01",
                    "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
                }
            ],
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert reply.reply == "我昨天开始疼的。"
    assert reply.fact_ids_used == ["appendicitis_001.hf_01"]
    assert fake_client.calls[0]["payload"]["answerable_fact_candidates"][0]["fact_id"] == "fact_1"


def test_patient_provider_payload_contains_only_current_answerable_facts() -> None:
    hidden_fact = "有恶心，没吐出来，低热约 37.8 ℃。"
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(reply="我昨天开始疼的。", fact_ids_used=["fact_1"])
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )

    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="什么时候开始疼？",
            current_intents=["ask_onset"],
            canonical_answer="24 小时前开始，最初是上腹部隐痛。",
            revealed_fact_id="appendicitis_001.hf_01",
            revealed_fact_ids=["appendicitis_001.hf_01"],
            patient_private_context={
                "history": {
                    "present_illness_summary": f"完整摘要：{hidden_fact}",
                    "hidden_facts": [{"fact_id": "appendicitis_001.hf_05", "canonical_answer": hidden_fact}],
                }
            },
            answerable_fact_candidates=[
                {
                    "fact_id": "appendicitis_001.hf_01",
                    "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
                    "source_reference": "case:appendicitis_001.history.appendicitis_001.hf_01",
                }
            ],
            forbidden_terms=["急性阑尾炎", "appendicitis"],
            forbidden_context={"diagnosis_terms": ["急性阑尾炎"]},
            protected_fact_texts=[hidden_fact],
            deterministic_hints={
                "revealed_fact_ids": ["appendicitis_001.hf_01"],
                "answerable_fact_ids": ["appendicitis_001.hf_01"],
            },
        )
    )

    provider_payload = fake_client.calls[0]["payload"]
    payload_text = str(provider_payload)
    assert reply.fact_ids_used == ["appendicitis_001.hf_01"]
    assert provider_payload["canonical_answer"] == ""
    assert (
        provider_payload["answerable_fact_candidates"][0]["canonical_answer"]
        == "24 小时前开始，最初是上腹部隐痛。"
    )
    assert "patient_private_context" not in provider_payload
    assert "forbidden_terms" not in provider_payload
    assert "forbidden_context" not in provider_payload
    assert "protected_fact_texts" not in provider_payload
    assert "appendicitis_001" not in payload_text
    assert "急性阑尾炎" not in payload_text
    assert hidden_fact not in payload_text
    assert "present_illness_summary" not in payload_text


def test_patient_provider_payload_includes_only_deidentified_role_skill_policy() -> None:
    request = module.PatientResponderRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        student_message="你现在最担心什么？",
        current_intents=["ask_ideas_concerns_expectations"],
        canonical_answer="我有点害怕是不是很严重。",
        forbidden_terms=["急性阑尾炎"],
        role_skill_policy={
            "version": "skill_role_policy.v1",
            "role": "patient",
            "active": True,
            "practice_focus": ["让当前已存在的患者情绪更容易被学生感知和回应"],
            "constraints": ["表达风格不得决定或新增病例事实"],
        },
    )

    provider_payload, _ = module._build_patient_provider_payload(request)

    assert provider_payload["role_skill_policy"]["active"] is True
    payload_text = str(provider_payload)
    assert "skill_role_policy.v1" in payload_text
    assert "skill_id" not in payload_text
    assert "suggested_strategy" not in payload_text
    assert "rubric" not in payload_text.casefold()
    assert "急性阑尾炎" not in payload_text


def _large_patient_fact_request() -> module.PatientResponderRequest:
    facts = [
        {
            "fact_id": f"large_case.hf_{index:02d}",
            "topic": f"同一问诊主题 {index:02d} 🩺",
            "slot": "same_intent_slot",
            "canonical_answer": (
                f"唯一事实标记<{index:02d}>😀："
                + "这是包含中文与 emoji 的很长病例事实。"
                * 180
            ),
            "variants": [
                (
                    f"唯一事实标记<{index:02d}>😀："
                    + "这是包含中文与 emoji 的很长病例事实。"
                    * 180
                ),
                f"未选事实口语标记<{index:02d}>🧑‍⚕️",
                f"未选事实口语标记<{index:02d}>🧑‍⚕️",
                f"备用口语标记<{index:02d}>🙂：" + "还是很长的口语表达。" * 120,
            ],
            "trigger_intents": ["ask_same_intent"],
        }
        for index in range(36)
    ]
    return module.PatientResponderRequest(
        case_id="large_case",
        case_title="中文😀超长病例",
        chief_complaint="反复不适，需要逐项追问。",
        student_message="这些情况都是什么样的？🙂",
        current_intents=["ask_same_intent"],
        canonical_answer="；".join(str(fact["canonical_answer"]) for fact in facts),
        answerable_fact_candidates=facts,
        forbidden_terms=["禁止诊断词"],
    )


def test_patient_provider_payload_is_utf8_bounded_deterministic_and_omits_unselected_facts() -> None:
    request = _large_patient_fact_request()

    first_payload, first_fact_id_map = module._build_patient_provider_payload(request)
    second_payload, second_fact_id_map = module._build_patient_provider_payload(request)

    serialized = json.dumps(first_payload, ensure_ascii=False)
    selected_original_ids = set(first_fact_id_map.values())
    assert len(serialized.encode("utf-8")) <= module.PATIENT_PROVIDER_CONTENT_BUDGET_BYTES
    assert (
        module.MAX_PATIENT_PROVIDER_PAYLOAD_BYTES
        - len(serialized.encode("utf-8"))
        >= module.PATIENT_PROVIDER_ENVELOPE_RESERVE_BYTES
    )
    assert first_payload == second_payload
    assert first_fact_id_map == second_fact_id_map
    assert 0 < len(first_fact_id_map) < len(request.answerable_fact_candidates)
    assert list(first_fact_id_map) == [
        f"fact_{index}"
        for index in range(1, len(first_fact_id_map) + 1)
    ]
    assert "😀" in serialized

    first_candidate = first_payload["answerable_fact_candidates"][0]
    assert first_candidate["canonical_answer"] not in first_candidate.get("variants", [])
    assert len(first_candidate.get("variants", [])) == 2

    for index, candidate in enumerate(request.answerable_fact_candidates):
        original_fact_id = str(candidate["fact_id"])
        canonical_marker = f"唯一事实标记<{index:02d}>😀"
        variant_marker = f"未选事实口语标记<{index:02d}>🧑‍⚕️"
        if original_fact_id in selected_original_ids:
            assert canonical_marker in serialized
        else:
            assert original_fact_id not in serialized
            assert canonical_marker not in serialized
            assert variant_marker not in serialized


def test_patient_fact_selection_reserves_a_candidate_for_each_current_intent() -> None:
    candidates = [
        {
            "fact_id": f"case.hf_location_{index:02d}",
            "canonical_answer": f"部位事实 {index}",
            "trigger_intents": ["ask_location"],
        }
        for index in range(20)
    ]
    candidates.append(
        {
            "fact_id": "case.hf_severity",
            "canonical_answer": "疼痛程度事实",
            "trigger_intents": ["ask_severity"],
        }
    )

    selected = module.select_patient_provider_fact_candidates(
        candidates,
        ["ask_location", "ask_severity"],
    )

    assert selected[0]["fact_id"] == "case.hf_location_00"
    assert selected[-1]["fact_id"] == "case.hf_severity"
    assert len(selected) == module.MAX_PATIENT_PROVIDER_FACT_CANDIDATES


def test_patient_responder_rejects_text_from_fact_omitted_by_provider_budget() -> None:
    request = _large_patient_fact_request()
    _, provider_fact_id_map = module._build_patient_provider_payload(request)
    omitted_index = next(
        index
        for index, candidate in enumerate(request.answerable_fact_candidates)
        if str(candidate["fact_id"]) not in set(provider_fact_id_map.values())
    )
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(
            reply=f"未选事实口语标记<{omitted_index:02d}>🧑‍⚕️",
            fact_ids_used=["fact_1"],
        )
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(
            enabled=True,
            api_key="key",
            model="model",
        ),
        client=fake_client,
    )

    with pytest.raises(RuntimeError, match="未授权病例事实"):
        responder(request)


def test_patient_responder_rejects_protected_fact_text_when_fact_ids_used_is_empty() -> None:
    hidden_fact = "有恶心，没吐出来，低热约 37.8 ℃。"
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(reply=hidden_fact, fact_ids_used=[])
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )

    request = module.PatientResponderRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        student_message="什么时候开始疼？",
        current_intents=["ask_onset"],
        canonical_answer="24 小时前开始，最初是上腹部隐痛。",
        answerable_fact_candidates=[
            {
                "fact_id": "appendicitis_001.hf_01",
                "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
            }
        ],
        protected_fact_texts=[hidden_fact],
        forbidden_terms=["急性阑尾炎"],
    )

    with pytest.raises(RuntimeError, match="未授权病例事实|未声明本轮病例事实"):
        responder(request)


def test_patient_responder_rejects_forbidden_terms_case_insensitively() -> None:
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(reply="This looks like APPENDICITIS.", fact_ids_used=["fact_1"])
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )
    request = module.PatientResponderRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        student_message="什么时候开始疼？",
        current_intents=["ask_onset"],
        canonical_answer="24 小时前开始，最初是上腹部隐痛。",
        answerable_fact_candidates=[
            {
                "fact_id": "appendicitis_001.hf_01",
                "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
            }
        ],
        forbidden_terms=["appendicitis"],
    )

    with pytest.raises(RuntimeError, match="禁止泄露词"):
        responder(request)


def test_patient_responder_keeps_model_declared_emotion() -> None:
    fake_client = FakePatientFactIdClient(
        module.PatientResponderResponse(
            reply="我怕这个病会不会很严重。",
            emotion="anxious",
            fact_ids_used=["fact_1"],
        )
    )
    responder = module.OpenAICompatiblePatientResponder(
        settings=openai_module.OpenAICompatibleSettings(enabled=True, api_key="key", model="model"),
        client=fake_client,
    )

    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="你现在担心什么？",
            current_intents=["ask_ideas_concerns_expectations"],
            canonical_answer="担心是不是要开刀。",
            revealed_fact_id="appendicitis_001.hf_01",
            answerable_fact_candidates=[
                {
                    "fact_id": "appendicitis_001.hf_01",
                    "canonical_answer": "担心是不是要开刀。",
                }
            ],
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert reply.reply == "我怕这个病会不会很严重。"
    assert reply.emotion == "焦虑"


def test_create_configured_patient_responder_uses_vertex_adc_without_api_key(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "true")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_PROJECT", "demo-project")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_LOCATION", "global")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_API_KEY", "")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_PROXY_URL", "http://server-managed-proxy.example:8080")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")

    responder = module._create_configured_responder()

    assert responder._settings.api_key == ""
    assert responder._settings.use_vertex is True
    assert responder._settings.project == "demo-project"
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-3.1-pro-preview"
    client_kwargs = captured_clients[0].kwargs
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    http_options = client_kwargs["http_options"]
    assert http_options.client_args == {
        "follow_redirects": False,
        "trust_env": False,
        "proxy": "http://server-managed-proxy.example:8080",
    }
    assert http_options.async_client_args["trust_env"] is False
    assert http_options.async_client_args["proxy"] == "http://server-managed-proxy.example:8080"
    assert os.environ.get("HTTP_PROXY") is None
    assert os.environ.get("HTTPS_PROXY") is None
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7897"


class FakeOpenAICompatiblePatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"reply":"我右下腹疼得比较明显。"}',
                    },
                }
            ],
        }


class FakeOpenAICompatiblePatientReplyKeyResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"patient_reply":"现在是持续性的胀痛，走路的时候会更疼一些。"}',
                    },
                }
            ],
        }


class FakeOpenAICompatibleHttpClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeOpenAICompatibleHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatiblePatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatiblePatientResponse()


class FakeOpenAICompatiblePatientReplyKeyHttpClient(FakeOpenAICompatibleHttpClient):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatiblePatientReplyKeyResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatiblePatientReplyKeyResponse()


class FakePlainTextOpenAICompatiblePatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "开始时上腹部疼，现在右下腹最疼。",
                    },
                }
            ],
        }


class FakePlainTextOpenAICompatibleHttpClient(FakeOpenAICompatibleHttpClient):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakePlainTextOpenAICompatiblePatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakePlainTextOpenAICompatiblePatientResponse()


class FakeAnthropicPatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"reply":"我右下腹疼得比较明显。"}',
                }
            ],
        }


class FakeAnthropicHttpClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeAnthropicHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeAnthropicPatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeAnthropicPatientResponse()


class FakePlainTextAnthropicPatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "开始时上腹部疼，现在右下腹最疼。",
                }
            ],
        }


class FakePlainTextAnthropicHttpClient(FakeAnthropicHttpClient):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakePlainTextAnthropicPatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakePlainTextAnthropicPatientResponse()


def test_create_configured_patient_responder_uses_runtime_openai_compatible_config(monkeypatch) -> None:
    FakeOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "gemini-via-clprox",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakeOpenAICompatibleHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里疼？",
                current_intents=["ask_location"],
                canonical_answer="右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply.reply == "我右下腹疼得比较明显。"
    assert FakeOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert FakeOpenAICompatibleHttpClient.calls[0]["headers"]["Authorization"] == "Bearer student-openai-secret"
    assert FakeOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "gemini-via-clprox"


def test_openai_compatible_patient_responder_accepts_patient_reply_key(monkeypatch) -> None:
    FakeOpenAICompatiblePatientReplyKeyHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "mimo-v2.5-pro",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakeOpenAICompatiblePatientReplyKeyHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="右下腹部有多痛？怎么个痛法？",
                current_intents=["ask_character"],
                canonical_answer="现在是持续性胀痛，走路或咳嗽时疼痛加重。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply.reply == "现在是持续性的胀痛，走路的时候会更疼一些。"
    assert "patient_reply" not in reply.reply


def test_openai_compatible_patient_responder_accepts_plain_text_reply_for_single_field_schema(monkeypatch) -> None:
    FakePlainTextOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "mimo-v2.5-pro",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakePlainTextOpenAICompatibleHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里最疼？",
                current_intents=["ask_location"],
                canonical_answer="现在右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply.reply == "开始时上腹部疼，现在右下腹最疼。"
    assert FakePlainTextOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"


def test_create_configured_patient_responder_uses_runtime_anthropic_config(monkeypatch) -> None:
    FakeAnthropicHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(anthropic_module.httpx, "Client", FakeAnthropicHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里疼？",
                current_intents=["ask_location"],
                canonical_answer="右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply.reply == "我右下腹疼得比较明显。"
    assert FakeAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert FakeAnthropicHttpClient.calls[0]["headers"]["x-api-key"] == "student-anthropic-secret"
    assert FakeAnthropicHttpClient.calls[0]["headers"]["anthropic-version"] == "2023-06-01"
    assert FakeAnthropicHttpClient.calls[0]["json"]["model"] == "claude-3-5-sonnet-latest"


def test_anthropic_patient_responder_accepts_plain_text_reply_for_single_field_schema(monkeypatch) -> None:
    FakePlainTextAnthropicHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "mimo-v2.5-pro",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(anthropic_module.httpx, "Client", FakePlainTextAnthropicHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里最疼？",
                current_intents=["ask_location"],
                canonical_answer="现在右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply.reply == "开始时上腹部疼，现在右下腹最疼。"
    assert FakePlainTextAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"


def test_create_configured_patient_responder_uses_runtime_vertex_gemini_adc_config(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        responder = module._create_configured_responder()
    finally:
        runtime_model_config_store.clear()

    assert responder._settings.use_vertex is True
    assert responder._settings.project == "demo-project"
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-3.1-pro-preview"
    client_kwargs = captured_clients[0].kwargs
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
    }
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert os.environ.get("HTTP_PROXY") is None
    assert os.environ.get("HTTPS_PROXY") is None


def test_create_configured_patient_responder_uses_runtime_vertex_gemini_api_key_config(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_api_key",
            "api_key": "student-vertex-secret",
            "model": "gemini-2.5-flash",
            "base_url": "",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
    finally:
        runtime_model_config_store.clear()

    assert responder._settings.use_vertex is True
    assert responder._settings.api_key == "student-vertex-secret"
    assert responder._settings.project == ""
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-2.5-flash"
    client_kwargs = captured_clients[0].kwargs
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "api_key": "student-vertex-secret",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
        "proxy": "http://127.0.0.1:7897",
    }
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert client_kwargs["http_options"].async_client_args["proxy"] == "http://127.0.0.1:7897"
