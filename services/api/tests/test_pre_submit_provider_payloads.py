import json

from app.services import procedure_request_router as router_module
from app.services import procedure_result_approval_agent as approval_module
from app.services import procedure_result_simulator as simulator_module


class RecordingClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def test_procedure_router_provider_payload_excludes_case_secrets_and_denylist() -> None:
    recording_client = RecordingClient(router_module.ProcedureRequestRoutingResponse())
    router = router_module.OpenAICompatibleProcedureRequestRouter(object(), client=recording_client)

    router(
        router_module.ProcedureRequestRoutingRequest(
            case_id="appendicitis_001",
            case_title="急性阑尾炎训练病例",
            chief_complaint="右下腹痛",
            request_text="我想查心电图",
            unmatched_requests=["心电图"],
            known_catalog_labels=["心电图"],
            forbidden_terms=["急性阑尾炎", "appendicitis"],
        )
    )

    provider_payload = recording_client.calls[0]["payload"]
    payload_text = str(provider_payload)
    assert provider_payload == {
        "request_text": "我想查心电图",
        "unmatched_requests": ["心电图"],
        "known_catalog_labels": ["心电图"],
    }
    assert "appendicitis_001" not in payload_text
    assert "急性阑尾炎" not in payload_text


def test_procedure_router_projects_only_bounded_lexical_catalog_neighbors() -> None:
    expected_response = router_module.ProcedureRequestRoutingResponse(
        routed_items=[
            router_module.ProcedureRequestRouteItem(
                raw_text="心脏电图🫀",
                decision="generate",
                kind="auxiliary_test",
                name_cn="心电图",
            )
        ]
    )
    recording_client = RecordingClient(expected_response)
    router = router_module.OpenAICompatibleProcedureRequestRouter(object(), client=recording_client)
    unrelated_labels = [
        f"无关目录{i:03d}-{'🧪' * 40}"
        for i in range(198)
    ]
    catalog_labels = [
        *unrelated_labels[:99],
        f"心脏电活动检查🫀-{'超长说明' * 80}",
        "心电图",
        *unrelated_labels[99:],
    ]
    assert len(catalog_labels) == 200

    response = router(
        router_module.ProcedureRequestRoutingRequest(
            case_id="case_001",
            case_title="教学病例",
            chief_complaint="不适",
            request_text="请帮我做心脏电图🫀",
            unmatched_requests=["心脏电图🫀"],
            known_catalog_labels=catalog_labels,
        )
    )

    provider_payload = recording_client.calls[0]["payload"]
    projected_labels = provider_payload["known_catalog_labels"]
    assert response == expected_response
    assert "心电图" in projected_labels
    assert any(label.startswith("心脏电活动") for label in projected_labels)
    assert not any(label.startswith("无关目录") for label in projected_labels)
    assert len(projected_labels) <= router_module.PROVIDER_CATALOG_LABEL_MAX_COUNT
    assert all(
        len(label.encode("utf-8")) <= router_module.PROVIDER_CATALOG_LABEL_MAX_BYTES
        for label in projected_labels
    )
    assert (
        len(json.dumps(projected_labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        <= router_module.PROVIDER_CATALOG_TOTAL_MAX_BYTES
    )
    assert all(label.encode("utf-8").decode("utf-8") == label for label in projected_labels)


def test_procedure_router_catalog_projection_is_stable_across_input_order() -> None:
    recording_client = RecordingClient(router_module.ProcedureRequestRoutingResponse())
    router = router_module.OpenAICompatibleProcedureRequestRouter(object(), client=recording_client)
    labels = [
        "心电图动态监测",
        "心电图",
        "超声心动图",
        "心脏电活动",
        "腹部超声",
        "尿常规",
    ]
    base_request = {
        "case_id": "case_001",
        "case_title": "教学病例",
        "chief_complaint": "不适",
        "request_text": "心脏电图",
        "unmatched_requests": ["心脏电图"],
    }

    router(router_module.ProcedureRequestRoutingRequest(**base_request, known_catalog_labels=labels))
    router(router_module.ProcedureRequestRoutingRequest(**base_request, known_catalog_labels=list(reversed(labels))))

    first_payload = recording_client.calls[0]["payload"]
    second_payload = recording_client.calls[1]["payload"]
    assert first_payload["known_catalog_labels"] == second_payload["known_catalog_labels"]
    assert "心电图" in first_payload["known_catalog_labels"]
    assert "腹部超声" not in first_payload["known_catalog_labels"]
    assert "尿常规" not in first_payload["known_catalog_labels"]


def test_procedure_simulator_provider_payload_excludes_private_case_truth() -> None:
    recording_client = RecordingClient(
        simulator_module.ProcedureResultSimulationResponse(
            result="未见明确异常。",
            safety_note="训练模拟，不参与评分。",
        )
    )
    simulator = simulator_module.OpenAICompatibleProcedureResultSimulator(object(), client=recording_client)

    simulator(
        simulator_module.ProcedureResultSimulationRequest(
            case_id="appendicitis_001",
            case_title="急性阑尾炎训练病例",
            chief_complaint="右下腹痛",
            request_text="我想查心电图",
            procedure_kind="auxiliary_test",
            procedure_code="ecg.st_segment",
            procedure_name_cn="心电图",
            patient_context={
                "present_illness_summary": "低热约 37.8 ℃。",
                "history_facts": [{"answer": "有恶心，没吐出来。"}],
            },
            configured_results=[
                {
                    "kind": "auxiliary_test",
                    "code": "lab.cbc",
                    "name_cn": "血常规",
                    "result": "白细胞 14.2×10^9/L。",
                }
            ],
            retrieved_knowledge_context=[
                {
                    "reference": "case:appendicitis_001",
                    "snippet": "急性阑尾炎可见右下腹压痛。",
                }
            ],
            forbidden_terms=["急性阑尾炎", "appendicitis"],
        )
    )

    provider_payload = recording_client.calls[0]["payload"]
    payload_text = str(provider_payload)
    assert provider_payload["request_text"] == "我想查心电图"
    assert provider_payload["procedure_name_cn"] == "心电图"
    assert "case_id" not in provider_payload
    assert "patient_context" not in provider_payload
    assert "configured_results" not in provider_payload
    assert "forbidden_terms" not in provider_payload
    assert "appendicitis_001" not in payload_text
    assert "急性阑尾炎" not in payload_text
    assert "白细胞 14.2" not in payload_text
    assert "37.8" not in payload_text


def test_procedure_approval_provider_payload_excludes_case_secrets_and_denylist() -> None:
    recording_client = RecordingClient(
        approval_module.ProcedureResultApprovalResponse(
            decision="approved",
            rationale="结果可作为训练参考。",
        )
    )
    approval_agent = approval_module.OpenAICompatibleProcedureResultApprovalAgent(
        object(),
        client=recording_client,
    )

    approval_agent(
        approval_module.ProcedureResultApprovalRequest(
            case_id="appendicitis_001",
            case_title="急性阑尾炎训练病例",
            chief_complaint="右下腹痛",
            request_text="我想查心电图",
            procedure_kind="auxiliary_test",
            procedure_code="ecg.st_segment",
            procedure_name_cn="心电图",
            simulated_result="窦性心律，未见明确异常。",
            source_context_references=["case:appendicitis_001", "rubric:appendicitis_001.ax_ecg"],
            forbidden_terms=["急性阑尾炎", "appendicitis"],
        )
    )

    provider_payload = recording_client.calls[0]["payload"]
    payload_text = str(provider_payload)
    assert provider_payload == {
        "request_text": "我想查心电图",
        "procedure_kind": "auxiliary_test",
        "procedure_code": "ecg.st_segment",
        "procedure_name_cn": "心电图",
        "simulated_result": "窦性心律，未见明确异常。",
    }
    assert "appendicitis_001" not in payload_text
    assert "急性阑尾炎" not in payload_text


def test_procedure_approval_provider_error_fails_closed(monkeypatch) -> None:
    class FailingApprovalAgent:
        def __call__(self, request: object) -> object:
            raise RuntimeError("approval provider unavailable")

    monkeypatch.setattr(
        approval_module,
        "_create_configured_approval_agent",
        lambda: FailingApprovalAgent(),
    )
    approval_agent = approval_module.LazyProcedureResultApprovalAgent()

    response = approval_agent(
        approval_module.ProcedureResultApprovalRequest(
            case_id="appendicitis_001",
            case_title="右下腹痛教学病例",
            chief_complaint="右下腹痛",
            request_text="我想查心电图",
            procedure_kind="auxiliary_test",
            procedure_code="ecg.st_segment",
            procedure_name_cn="心电图",
            simulated_result="窦性心律，未见明确异常。",
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert response.decision == "blocked"
    assert response.approval_mode == "llm_error_fail_closed"
    assert response.safety_issues == ["approval_agent_unavailable"]


def test_procedure_approval_local_gate_matches_forbidden_terms_case_insensitively() -> None:
    response = approval_module.DeterministicProcedureResultApprovalAgent()(
        approval_module.ProcedureResultApprovalRequest(
            case_id="appendicitis_001",
            case_title="右下腹痛教学病例",
            chief_complaint="右下腹痛",
            request_text="我想查心电图",
            procedure_kind="auxiliary_test",
            procedure_code="ecg.st_segment",
            procedure_name_cn="心电图",
            simulated_result="The result confirms APPENDICITIS.",
            forbidden_terms=["appendicitis"],
        )
    )

    assert response.decision == "blocked"
    assert response.approval_mode == "deterministic_safety_gate"
    assert response.safety_issues == ["包含受保护词：appendicitis"]
