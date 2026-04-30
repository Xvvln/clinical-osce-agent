import pytest
from fastapi.testclient import TestClient

from app import main
from app.graph.osce_graph import build_osce_graph
from app.main import AUTH_COOKIE_NAME, app
from app.services.auth_store import AuthStore
from app.services.osce_session_service import osce_session_service
from app.services.osce_session_store import OsceSessionStore
from app.services.report_store import ReportStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_store import TrainingSkillStore


client = TestClient(app)


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def assert_training_progress_hides_diagnosis(progress: dict[str, object]) -> None:
    progress_text = str(progress)
    assert "急性阑尾炎" not in progress_text
    assert "阑尾炎" not in progress_text
    assert "Acute appendicitis" not in progress_text
    assert "appendicitis" not in progress_text


@pytest.fixture(autouse=True)
def use_canonical_patient_responder() -> None:
    osce_session_service.osce_graph = build_osce_graph(patient_responder=canonical_patient_responder)


@pytest.fixture(autouse=True)
def authenticated_user(tmp_path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user("student@example.test", "safe-password-123", "学生甲")
    assert user is not None
    token = auth_store.create_session(user["user_id"])
    client.cookies.clear()
    client.cookies.set(AUTH_COOKIE_NAME, token)
    yield user
    client.cookies.clear()


def test_create_session_requires_logged_in_user() -> None:
    with TestClient(app) as anonymous_client:
        create_response = anonymous_client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert create_response.status_code == 401
    assert create_response.json() == {"detail": "not authenticated"}


def test_create_session_uses_authenticated_user_id(authenticated_user: dict[str, str]) -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "spoofed_student"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["student_id"] == authenticated_user["user_id"]


def session_operation_requests(session_id: str) -> list[tuple[str, str, dict[str, str] | None]]:
    return [
        ("GET", f"/api/sessions/{session_id}", None),
        ("POST", f"/api/sessions/{session_id}/message", {"message": "什么时候开始疼的？"}),
        ("POST", f"/api/sessions/{session_id}/physical-exam", {"exam_code": "abd.palpation.rebound"}),
        ("POST", f"/api/sessions/{session_id}/auxiliary-test", {"test_code": "lab.cbc"}),
        ("POST", f"/api/sessions/{session_id}/hypotheses", {"hypothesis": "急性阑尾炎"}),
        ("POST", f"/api/sessions/{session_id}/hint", None),
        (
            "POST",
            f"/api/sessions/{session_id}/submit-diagnosis",
            {"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
        ),
        ("GET", f"/api/sessions/{session_id}/report", None),
    ]


def test_session_operations_require_logged_in_user() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app) as anonymous_client:
        for method, path, json_body in session_operation_requests(session_id):
            response = anonymous_client.request(method, path, json=json_body)

            assert response.status_code == 401
            assert response.json() == {"detail": "not authenticated"}


def test_session_operations_reject_other_authenticated_user() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    other_user = main.auth_store.create_user("other-student@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        for method, path, json_body in session_operation_requests(session_id):
            response = other_client.request(method, path, json=json_body)

            assert response.status_code == 404
            assert response.json() == {"detail": "session not found"}


def test_current_user_sessions_require_logged_in_user() -> None:
    with TestClient(app) as anonymous_client:
        response = anonymous_client.get("/api/me/sessions")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_current_user_sessions_list_only_owned_sessions(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()
    current_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    other_user = main.auth_store.create_user("other-history@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.post("/api/sessions", json={"case_id": "pneumonia_001"})

    response = client.get("/api/me/sessions")

    assert current_response.status_code == 200
    assert other_response.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "session_id": current_response.json()["session_id"],
                "case_id": "appendicitis_001",
                "stage": "case_intro",
                "created_at": response.json()["sessions"][0]["created_at"],
                "updated_at": response.json()["sessions"][0]["updated_at"],
            }
        ]
    }
    assert response.json()["sessions"][0]["session_id"] != other_response.json()["session_id"]
    assert response.json()["sessions"][0]["created_at"]
    assert response.json()["sessions"][0]["updated_at"]


def test_current_user_profile_requires_logged_in_user() -> None:
    with TestClient(app) as anonymous_client:
        response = anonymous_client.get("/api/me/profile")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_current_user_profile_aggregates_only_owned_sessions_and_reports(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service._sessions.clear()
    current_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    current_session_id = current_response.json()["session_id"]
    client.post(f"/api/sessions/{current_session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{current_session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{current_session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{current_session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    current_report_response = client.get(f"/api/me/sessions/{current_session_id}/report")
    other_user = main.auth_store.create_user("other-profile@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.post("/api/sessions", json={"case_id": "pneumonia_001"})

    response = client.get("/api/me/profile")

    assert current_response.status_code == 200
    assert current_report_response.status_code == 200
    assert other_response.status_code == 200
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["student_id"] == authenticated_user["user_id"]
    assert profile["total_sessions"] == 1
    assert profile["report_count"] == 1
    assert profile["average_score"] == 32
    assert profile["recent_sessions"][0]["session_id"] == current_session_id
    assert profile["recent_sessions"][0]["session_id"] != other_response.json()["session_id"]
    assert profile["strongest_dimension"] == {"key": "main_diagnosis", "label": "主诊断", "average": 15}
    assert profile["weakest_dimension"] == {"key": "differential_diagnosis", "label": "鉴别诊断", "average": 0}
    assert profile["skill_accumulation"] == {
        "status": "planned",
        "description": "Step 8 接入已审核教学 Skill、错误模式和个性化提示策略。",
        "enabled_skill_count": 0,
        "applied_skill_count": 0,
        "enabled_skills": [],
    }


def test_current_user_profile_reports_enabled_and_applied_training_skills(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [],
            "review": {"status": "approved"},
        }
    )
    current_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    other_user = main.auth_store.create_user("other-skill-profile@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.post("/api/sessions", json={"case_id": "pneumonia_001"})

    response = client.get("/api/me/profile")

    assert current_response.status_code == 200
    assert other_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["profile"]["skill_accumulation"] == {
        "status": "active",
        "description": "已启用 1 条教学 Skill，并在当前账号训练中应用 1 次。",
        "enabled_skill_count": 1,
        "applied_skill_count": 1,
        "enabled_skills": [
            {
                "skill_id": "skill_reasoning_core",
                "title": "临床推理链纠偏提示",
                "trigger_item_id": "reasoning_core",
                "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
                "support_count": 2,
            }
        ],
    }



def test_current_user_session_detail_and_report_require_logged_in_user() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app) as anonymous_client:
        detail_response = anonymous_client.get(f"/api/me/sessions/{session_id}")
        report_response = anonymous_client.get(f"/api/me/sessions/{session_id}/report")

    assert detail_response.status_code == 401
    assert detail_response.json() == {"detail": "not authenticated"}
    assert report_response.status_code == 401
    assert report_response.json() == {"detail": "not authenticated"}


def test_current_user_session_detail_and_report_use_owned_session() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    other_user = main.auth_store.create_user("other-detail@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    detail_response = client.get(f"/api/me/sessions/{session_id}")
    report_response = client.get(f"/api/me/sessions/{session_id}/report")

    assert detail_response.status_code == 200
    assert detail_response.json()["session_id"] == session_id
    assert report_response.status_code == 200
    assert report_response.json()["session_id"] == session_id

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_detail_response = other_client.get(f"/api/me/sessions/{session_id}")
        other_report_response = other_client.get(f"/api/me/sessions/{session_id}/report")

    assert other_detail_response.status_code == 404
    assert other_detail_response.json() == {"detail": "session not found"}
    assert other_report_response.status_code == 404
    assert other_report_response.json() == {"detail": "session not found"}


def test_current_user_can_delete_only_owned_session(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    other_user = main.auth_store.create_user("other-delete@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as anonymous_client:
        anonymous_response = anonymous_client.delete(f"/api/me/sessions/{session_id}")

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.delete(f"/api/me/sessions/{session_id}")

    delete_response = client.delete(f"/api/me/sessions/{session_id}")
    detail_response = client.get(f"/api/me/sessions/{session_id}")
    list_response = client.get("/api/me/sessions")

    assert anonymous_response.status_code == 401
    assert anonymous_response.json() == {"detail": "not authenticated"}
    assert other_response.status_code == 404
    assert other_response.json() == {"detail": "session not found"}
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "session_id": session_id}
    assert detail_response.status_code == 404
    assert detail_response.json() == {"detail": "session not found"}
    assert list_response.status_code == 200
    assert list_response.json() == {"sessions": []}


def test_create_session_returns_case_specific_diagnosis_draft() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "pneumonia_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["case_id"] == "pneumonia_001"
    assert created["diagnosis_draft"] == {
        "diagnosis": "社区获得性肺炎",
        "reasoning": "发热、咳嗽、黄痰和呼吸相关胸痛提示下呼吸道感染。体温升高及右下肺湿啰音支持肺部感染体征。血常规炎症指标升高且胸片见右下肺浸润影，支持社区获得性肺炎。",
    }


def test_create_session_returns_student_visible_patient_profile() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    patient_profile = create_response.json()["patient_profile"]
    assert patient_profile == {
        "age": "22岁",
        "gender": "男",
        "occupation": "学生",
        "hospital_department": "急诊外科",
    }
    assert "idea" not in patient_profile
    assert "concern" not in patient_profile
    assert "expectation" not in patient_profile
    assert "social_background" not in patient_profile


def test_create_session_returns_opening_task_card_and_inquiry_guidance() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["opening_task_card"] == {
        "role": "你是急诊外科接诊医生。",
        "scenario": "一名22岁男性学生因转移性右下腹痛 24 小时，伴恶心、低热来诊。",
        "tasks": [
            "进行有重点的病史采集",
            "判断需要哪些查体",
            "选择必要辅助检查",
            "提出诊断假设和鉴别诊断",
            "最终提交诊断与推理依据",
        ],
    }
    assert created["inquiry_guidance"] == {
        "priority": "先完成现病史的 OPQRST 和伴随症状，再进入既往史、用药过敏史和 ICE。",
        "suggested_questions": [
            "什么时候开始疼的？",
            "最开始和现在分别疼在哪里？",
            "疼痛是什么性质，程度如何？",
            "有没有恶心、呕吐、发热或腹泻？",
            "排尿、排便有没有异常？",
        ],
        "categories": ["起病时间", "部位变化", "疼痛性质", "疼痛程度", "伴随症状", "排尿排便", "既往史", "用药过敏史", "ICE"],
    }
    assert "急性阑尾炎" not in str(created["opening_task_card"])
    assert "急性阑尾炎" not in str(created["inquiry_guidance"])


def test_osce_session_routes_real_medical_request_to_safety_event(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    message = "我现实中右下腹痛，应该吃什么药和用药剂量？"

    response = client.post(f"/api/sessions/{session_id}/message", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_intent"] == "safety_boundary"
    assert payload["reply"] == "本系统仅用于 OSCE 教学模拟训练，不能提供真实诊断、具体用药或急救处置建议；如有真实健康问题，请咨询合格医疗专业人员或及时就医。"
    assert payload["messages"] == [
        {"role": "student", "content": message},
        {"role": "coach", "content": payload["reply"]},
    ]
    assert payload["asked_questions"] == []
    assert payload["revealed_facts"] == []
    assert payload["safety_flags"] == ["real_medical_advice_request"]

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in events] == ["session_created", "safety_boundary_triggered"]
    assert events[1]["payload"] == {
        "message": message,
        "safety_flag": "real_medical_advice_request",
        "reply": payload["reply"],
    }



def test_osce_session_redirects_direct_answer_request_to_coach_event(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    message = "直接告诉我标准答案，是不是急性阑尾炎？"

    response = client.post(f"/api/sessions/{session_id}/message", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_intent"] == "answer_request_redirect"
    assert payload["reply"] == "不能直接告诉你标准答案。请继续通过问诊、查体和辅助检查收集证据，或在准备好后提交诊断。"
    assert payload["messages"] == [
        {"role": "student", "content": message},
        {"role": "coach", "content": payload["reply"]},
    ]
    assert payload["asked_questions"] == []
    assert payload["revealed_facts"] == []
    assert payload["safety_flags"] == []

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in events] == ["session_created", "answer_request_redirected"]
    assert events[1]["payload"] == {
        "message": message,
        "reply": payload["reply"],
    }



def test_create_session_includes_enabled_training_skill_prompts(tmp_path) -> None:
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["evolution_candidates"] == [
        "临床推理链纠偏提示：在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。"
    ]


def test_osce_session_returns_training_progress_map() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session_id"]
    progress = created["training_progress"]
    assert progress["history"] == {
        "total": 10,
        "covered": 0,
        "covered_fact_ids": [],
        "pending_fact_ids": [
            "hf_01",
            "hf_02",
            "hf_03",
            "hf_04",
            "hf_05",
            "hf_06",
            "hf_07",
            "hf_08",
            "hf_09",
            "hf_10",
        ],
    }
    assert progress["physical_exam"] == {
        "total": 7,
        "requested": 0,
        "requested_codes": [],
        "pending_codes": [
            "vital.temperature",
            "abd.inspection",
            "abd.palpation.tenderness",
            "abd.palpation.rebound",
            "abd.palpation.guarding",
            "abd.special.rovsing",
            "abd.special.psoas",
        ],
        "must_total": 4,
        "must_requested": 0,
        "must_pending_codes": [
            "vital.temperature",
            "abd.inspection",
            "abd.palpation.tenderness",
            "abd.palpation.rebound",
        ],
    }
    assert progress["auxiliary_test"] == {
        "total": 5,
        "requested": 0,
        "requested_codes": [],
        "pending_codes": ["lab.cbc", "lab.crp", "img.abd_us", "lab.urinalysis", "img.abd_ct"],
        "must_total": 3,
        "must_requested": 0,
        "must_pending_codes": ["lab.cbc", "lab.crp", "img.abd_us"],
    }
    assert progress["reasoning"] == {
        "total_evidence": 13,
        "collected_evidence_count": 0,
        "collected_evidence": [],
        "pending_evidence": [
            "hf_02",
            "abd.palpation.tenderness",
            "abd.palpation.rebound",
            "abd.palpation.guarding",
            "abd.special.rovsing",
            "lab.cbc",
            "lab.crp",
            "img.abd_us",
            "img.abd_ct",
            "lab.urinalysis",
            "hf_08",
            "vital.temperature",
            "abd.inspection",
        ],
        "ready_for_hypothesis": False,
    }
    assert progress["next_focus"] == "先用开放式问题明确起病、部位、性质、程度和伴随症状。"
    assert progress["coverage_map"]["history"][0] == {
        "id": "hf_01",
        "label": "24 小时前开始，最初是上腹部隐痛。",
        "status": "pending",
    }
    assert progress["coverage_map"]["physical_exam"][2] == {
        "id": "abd.palpation.tenderness",
        "label": "McBurney 点压痛：右下腹 McBurney 点明显压痛。",
        "status": "pending",
    }
    assert progress["coverage_map"]["auxiliary_test"][0] == {
        "id": "lab.cbc",
        "label": "血常规：白细胞 14.2×10^9/L，中性粒细胞比例 85%。",
        "status": "pending",
    }
    assert progress["coverage_map"]["reasoning"][0] == {
        "id": "hf_02",
        "label": "开始在上腹部，大约 8 小时前转移并固定到右下腹。",
        "status": "pending",
    }
    assert_training_progress_hides_diagnosis(progress)

    message_response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "什么时候开始疼的？"},
    )

    assert message_response.status_code == 200
    message_progress = message_response.json()["training_progress"]
    assert_training_progress_hides_diagnosis(message_progress)
    history_progress = message_progress["history"]
    assert history_progress["covered"] == 1
    assert history_progress["covered_fact_ids"] == ["hf_01"]
    assert "hf_01" not in history_progress["pending_fact_ids"]

    exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exam",
        json={"exam_code": "abd.palpation.rebound"},
    )

    assert exam_response.status_code == 200
    exam_progress = exam_response.json()["training_progress"]
    assert_training_progress_hides_diagnosis(exam_progress)
    assert exam_progress["physical_exam"]["requested"] == 1
    assert exam_progress["physical_exam"]["requested_codes"] == ["abd.palpation.rebound"]
    assert exam_progress["reasoning"]["collected_evidence"] == ["abd.palpation.rebound"]
    assert exam_progress["next_focus"] == "你已经获得部分病史和查体信息，可以申请能验证当前假设的辅助检查。"

    test_response = client.post(
        f"/api/sessions/{session_id}/auxiliary-test",
        json={"test_code": "lab.cbc"},
    )

    assert test_response.status_code == 200
    test_progress = test_response.json()["training_progress"]
    assert_training_progress_hides_diagnosis(test_progress)
    assert test_progress["auxiliary_test"]["requested"] == 1
    assert test_progress["auxiliary_test"]["requested_codes"] == ["lab.cbc"]
    assert test_progress["reasoning"]["collected_evidence"] == ["abd.palpation.rebound", "lab.cbc"]
    assert test_progress["reasoning"]["ready_for_hypothesis"] is True
    assert test_progress["next_focus"] == "已有病史、查体和辅助检查证据，先记录一个诊断假设，再继续补齐关键证据。"


def test_osce_session_minimal_training_loop(authenticated_user: dict[str, str]) -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session_id"]
    assert created["case_id"] == "appendicitis_001"
    assert created["student_id"] == authenticated_user["user_id"]
    assert created["stage"] == "case_intro"
    assert created["case_title"] == "右下腹痛教学病例"
    assert created["chief_complaint"] == "转移性右下腹痛 24 小时，伴恶心、低热"
    assert created["diagnosis_draft"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛是急性阑尾炎的典型症状。McBurney 点压痛、反跳痛、肌紧张和 Rovsing 征提示右下腹腹膜刺激征。白细胞升高伴 CRP 升高支持炎症性腹痛。腹部超声或腹部 CT 的阑尾异常表现支持阑尾区炎症。尿常规阴性有助于排除输尿管结石。男性患者可直接排除异位妊娠。低热和腹部呼吸运动减弱支持局部炎症刺激。",
    }
    assert created["physical_exam_options"] == [
        {
            "exam_code": "vital.temperature",
            "exam_name_cn": "体温",
            "result": "37.8 ℃。",
            "is_abnormal": True,
        },
        {
            "exam_code": "abd.inspection",
            "exam_name_cn": "腹部视诊",
            "result": "腹平坦，无胃肠型，呼吸运动减弱。",
            "is_abnormal": True,
        },
        {
            "exam_code": "abd.palpation.tenderness",
            "exam_name_cn": "McBurney 点压痛",
            "result": "右下腹 McBurney 点明显压痛。",
            "is_abnormal": True,
        },
        {
            "exam_code": "abd.palpation.rebound",
            "exam_name_cn": "反跳痛（Blumberg 征）",
            "result": "右下腹反跳痛阳性。",
            "is_abnormal": True,
        },
        {
            "exam_code": "abd.palpation.guarding",
            "exam_name_cn": "肌紧张",
            "result": "右下腹轻度肌紧张。",
            "is_abnormal": True,
        },
        {
            "exam_code": "abd.special.rovsing",
            "exam_name_cn": "Rovsing 征",
            "result": "Rovsing 征阳性。",
            "is_abnormal": True,
        },
        {
            "exam_code": "abd.special.psoas",
            "exam_name_cn": "腰大肌征",
            "result": "腰大肌征阴性。",
            "is_abnormal": False,
        },
    ]
    assert created["auxiliary_test_options"] == [
        {
            "test_code": "lab.cbc",
            "test_name_cn": "血常规",
            "category": "实验室",
            "result": "白细胞 14.2×10^9/L，中性粒细胞比例 85%。",
            "is_abnormal": True,
        },
        {
            "test_code": "lab.crp",
            "test_name_cn": "C 反应蛋白",
            "category": "实验室",
            "result": "CRP 48 mg/L。",
            "is_abnormal": True,
        },
        {
            "test_code": "img.abd_us",
            "test_name_cn": "腹部超声",
            "category": "影像",
            "result": "右下腹见管状低回声结构，直径 9 mm，周围少量渗出。",
            "is_abnormal": True,
        },
        {
            "test_code": "lab.urinalysis",
            "test_name_cn": "尿常规",
            "category": "实验室",
            "result": "尿常规阴性，未见血尿。",
            "is_abnormal": False,
        },
        {
            "test_code": "img.abd_ct",
            "test_name_cn": "腹部 CT",
            "category": "影像",
            "result": "阑尾增粗，周围脂肪间隙模糊。",
            "is_abnormal": True,
        },
    ]

    message_response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "什么时候开始疼的？"},
    )

    assert message_response.status_code == 200
    message_payload = message_response.json()
    assert "24 小时前开始" in message_payload["reply"]
    assert "急性阑尾炎" not in message_payload["reply"]
    assert "appendicitis_001.hf_01" in message_payload["revealed_facts"]

    exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exam",
        json={"exam_code": "abd.palpation.rebound"},
    )

    assert exam_response.status_code == 200
    exam_payload = exam_response.json()
    assert exam_payload["exam_code"] == "abd.palpation.rebound"
    assert exam_payload["result"] == "右下腹反跳痛阳性。"
    assert "abd.palpation.rebound" in exam_payload["requested_exams"]

    test_response = client.post(
        f"/api/sessions/{session_id}/auxiliary-test",
        json={"test_code": "lab.cbc"},
    )

    assert test_response.status_code == 200
    test_payload = test_response.json()
    assert test_payload["test_code"] == "lab.cbc"
    assert test_payload["result"] == "白细胞 14.2×10^9/L，中性粒细胞比例 85%。"
    assert "lab.cbc" in test_payload["requested_tests"]

    submit_response = client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )

    assert submit_response.status_code == 200
    submit_payload = submit_response.json()
    assert submit_payload["stage"] == "diagnosis_submission"
    assert submit_payload["final_submission"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
    }

    state_response = client.get(f"/api/sessions/{session_id}")

    assert state_response.status_code == 200
    state_payload = state_response.json()
    assert state_payload["stage"] == "diagnosis_submission"
    assert state_payload["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert state_payload["requested_exams"] == ["abd.palpation.rebound"]
    assert state_payload["requested_tests"] == ["lab.cbc"]

    report_response = client.get(f"/api/sessions/{session_id}/report")

    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["session_id"] == session_id
    assert report_payload["case_id"] == "appendicitis_001"
    assert report_payload["total_score"] == 32
    assert report_payload["dimension_scores"] == {
        "history_taking": 3,
        "physical_exam": 5,
        "auxiliary_test": 5,
        "main_diagnosis": 15,
        "differential_diagnosis": 0,
        "reasoning": 4,
    }
    assert report_payload["rubric_scores"]["ht_onset"]["score"] == 3
    assert report_payload["rubric_scores"]["ht_migration"]["score"] == 0
    assert report_payload["rubric_scores"]["pe_rebound"]["score"] == 5
    assert report_payload["rubric_scores"]["ax_cbc"]["score"] == 5
    assert report_payload["rubric_scores"]["dx_main"]["score"] == 15
    assert report_payload["rubric_scores"]["rs_support"]["score"] == 4
    assert "ht_migration" in report_payload["missed_items"]
    assert report_payload["strengths"] == [
        "追问起病时间：已完成。",
        "检查反跳痛：已完成。",
        "申请血常规：已完成。",
        "主要诊断命中急性阑尾炎：已完成。",
        "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）：已完成。",
    ]
    assert report_payload["reasoning_errors"] == [
        "提出输尿管结石并说明排除依据：评分轨迹未找到足够证据。",
        "提出克罗恩病并说明排除依据：评分轨迹未找到足够证据。",
        "考虑异位妊娠并正确排除：评分轨迹未找到足够证据。",
        "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）：评分轨迹未找到足够证据。",
        "推理表达覆盖关键排除依据：评分轨迹未找到足够证据。",
    ]
    assert report_payload["next_recommendations"] == [
        "下一轮训练重点：追问疼痛部位及转移特征。",
        "下一轮训练重点：追问疼痛性质。",
        "下一轮训练重点：追问疼痛程度。",
        "下一轮训练重点：追问恶心呕吐腹泻。",
        "下一轮训练重点：追问发热。",
        "下一轮训练重点：追问既往病史。",
        "下一轮训练重点：追问过敏史。",
        "下一轮训练重点：询问患者想法担忧与期望（ICE）。",
        "下一轮训练重点：测量体温。",
        "下一轮训练重点：腹部视诊。",
        "下一轮训练重点：检查腹部压痛。",
        "下一轮训练重点：申请 CRP。",
        "下一轮训练重点：申请腹部超声。",
        "下一轮训练重点：合理申请尿常规排除输尿管结石。",
        "下一轮训练重点：提出输尿管结石并说明排除依据。",
        "下一轮训练重点：提出克罗恩病并说明排除依据。",
        "下一轮训练重点：考虑异位妊娠并正确排除。",
        "下一轮训练重点：推理表达覆盖关键排除依据。",
    ]
    assert report_payload["source_references"] == [
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "rubric:appendicitis_001_rubric.item.ht_character",
        "rubric:appendicitis_001_rubric.item.ht_severity",
        "rubric:appendicitis_001_rubric.item.ht_associated_gi",
        "rubric:appendicitis_001_rubric.item.ht_associated_fever",
        "rubric:appendicitis_001_rubric.item.ht_past_medical",
        "rubric:appendicitis_001_rubric.item.ht_allergy",
        "rubric:appendicitis_001_rubric.item.ht_ice",
        "rubric:appendicitis_001_rubric.item.pe_vital_temp",
        "rubric:appendicitis_001_rubric.item.pe_abd_inspection",
        "rubric:appendicitis_001_rubric.item.pe_tenderness",
        "rubric:appendicitis_001_rubric.item.ax_crp",
        "rubric:appendicitis_001_rubric.item.ax_us",
        "rubric:appendicitis_001_rubric.item.ax_ua",
        "rubric:appendicitis_001_rubric.item.dxd_urolith",
        "rubric:appendicitis_001_rubric.item.dxd_crohn",
        "rubric:appendicitis_001_rubric.item.dxd_ectopic",
        "rubric:appendicitis_001_rubric.item.rs_exclude",
        "evidence:appendicitis_001.hf_01",
        "evidence:abd.palpation.rebound",
        "evidence:lab.cbc",
        "evidence:急性阑尾炎",
    ]
    assert report_payload["feedback_summary"] == "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。"
    report_text = str(report_payload)
    for forbidden_term in ["用药剂量", "治疗方案", "手术方案", "处置建议"]:
        assert forbidden_term not in report_text


def test_osce_session_records_diagnosis_hypothesis_before_final_submission(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "哪里最疼？"})

    hypothesis_response = client.post(
        f"/api/sessions/{session_id}/hypotheses",
        json={"hypothesis": "急性阑尾炎"},
    )

    assert hypothesis_response.status_code == 200
    payload = hypothesis_response.json()
    assert payload["stage"] == "history_taking"
    assert payload["student_hypotheses"] == ["急性阑尾炎"]
    assert payload["final_submission"] is None
    assert payload["rubric_scores"] == {}

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in events] == [
        "session_created",
        "history_message",
        "hypothesis_recorded",
    ]
    assert events[2]["payload"] == {"hypothesis": "急性阑尾炎"}


def test_osce_session_returns_socratic_hint_without_revealing_diagnosis(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})

    hint_response = client.post(f"/api/sessions/{session_id}/hint")

    assert hint_response.status_code == 200
    payload = hint_response.json()
    assert payload["stage"] == "history_taking"
    assert payload["hint"] == "已获得部分病史，下一步选择关键查体来验证当前线索。"
    assert payload["hint"] == payload["training_progress"]["next_focus"]
    assert payload["messages"][-1] == {"role": "coach", "content": payload["hint"]}
    assert payload["final_submission"] is None
    assert payload["rubric_scores"] == {}
    for forbidden_term in ["急性阑尾炎", "阑尾炎", "手术", "治疗方案"]:
        assert forbidden_term not in payload["hint"]

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in events] == [
        "session_created",
        "history_message",
        "hint_requested",
    ]
    assert events[2]["payload"] == {"hint": payload["hint"]}


def test_osce_session_uses_enabled_training_skill_when_requesting_socratic_hint(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})

    hint_response = client.post(f"/api/sessions/{session_id}/hint")

    assert hint_response.status_code == 200
    payload = hint_response.json()
    assert payload["hint"] == "本轮训练重点是临床推理链纠偏提示。提交诊断前，请按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。"
    assert payload["messages"][-1] == {"role": "coach", "content": payload["hint"]}
    assert payload["final_submission"] is None
    assert payload["rubric_scores"] == {}
    for forbidden_term in ["急性阑尾炎", "阑尾炎", "手术", "治疗方案"]:
        assert forbidden_term not in payload["hint"]

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in events] == [
        "session_created",
        "training_skill_applied",
        "history_message",
        "hint_requested",
    ]
    assert events[3]["payload"] == {"hint": payload["hint"]}


def test_session_report_can_be_read_after_session_memory_is_cleared(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    osce_session_service.report_store = ReportStore(database_path)
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]

    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    generated_report = client.get(f"/api/sessions/{session_id}/report").json()

    osce_session_service._sessions.clear()
    loaded_response = client.get(f"/api/sessions/{session_id}/report")

    assert loaded_response.status_code == 200
    assert loaded_response.json() == generated_report


def test_osce_session_state_can_be_read_after_session_memory_is_cleared(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]

    message_response = client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    exam_response = client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    hypothesis_response = client.post(
        f"/api/sessions/{session_id}/hypotheses",
        json={"hypothesis": "先考虑急腹症，需要继续查体和检查验证。"},
    )
    assert message_response.status_code == 200
    assert exam_response.status_code == 200
    assert hypothesis_response.status_code == 200

    osce_session_service._sessions.clear()
    loaded_response = client.get(f"/api/sessions/{session_id}")

    assert loaded_response.status_code == 200
    payload = loaded_response.json()
    assert payload["session_id"] == session_id
    assert payload["messages"] == message_response.json()["messages"]
    assert payload["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert payload["requested_exams"] == ["abd.palpation.rebound"]
    assert payload["student_hypotheses"] == ["先考虑急腹症，需要继续查体和检查验证。"]


def test_osce_session_records_training_events(tmp_path, authenticated_user: dict[str, str]) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]

    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    client.get(f"/api/sessions/{session_id}/report")

    events = TrainingEventStore(database_path).list_session_events(session_id)

    assert [event["event_type"] for event in events] == [
        "session_created",
        "training_skill_applied",
        "history_message",
        "physical_exam_requested",
        "auxiliary_test_requested",
        "diagnosis_submitted",
        "report_generated",
    ]
    assert events[0]["case_id"] == "appendicitis_001"
    assert events[0]["student_id"] == authenticated_user["user_id"]
    assert events[1]["payload"] == {
        "skill_id": "skill_reasoning_core",
        "title": "临床推理链纠偏提示",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
    }
    assert events[2]["payload"] == {
        "message": "什么时候开始疼的？",
        "current_intent": "ask_onset",
        "reply": "24 小时前开始，最初是上腹部隐痛。",
    }
    assert events[3]["payload"] == {"exam_code": "abd.palpation.rebound", "result": "右下腹反跳痛阳性。"}
    assert events[4]["payload"] == {"test_code": "lab.cbc", "result": "白细胞 14.2×10^9/L，中性粒细胞比例 85%。"}
    assert events[5]["payload"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
    }
    assert events[6]["payload"] == {
        "report_id": f"{session_id}_report",
        "total_score": 32,
        "missed_items": [
            "ht_migration",
            "ht_character",
            "ht_severity",
            "ht_associated_gi",
            "ht_associated_fever",
            "ht_past_medical",
            "ht_allergy",
            "ht_ice",
            "pe_vital_temp",
            "pe_abd_inspection",
            "pe_tenderness",
            "ax_crp",
            "ax_us",
            "ax_ua",
            "dxd_urolith",
            "dxd_crohn",
            "dxd_ectopic",
            "rs_exclude",
        ],
        "knowledge_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_migration",
                "title": "追问疼痛部位及转移特征",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_character",
                "title": "追问疼痛性质",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_severity",
                "title": "追问疼痛程度",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_associated_gi",
                "title": "追问恶心呕吐腹泻",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_associated_fever",
                "title": "追问发热",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_past_medical",
                "title": "追问既往病史",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_allergy",
                "title": "追问过敏史",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ht_ice",
                "title": "询问患者想法担忧与期望（ICE）",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.pe_vital_temp",
                "title": "测量体温",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.pe_abd_inspection",
                "title": "腹部视诊",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.pe_tenderness",
                "title": "检查腹部压痛",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ax_crp",
                "title": "申请 CRP",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ax_us",
                "title": "申请腹部超声",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.ax_ua",
                "title": "合理申请尿常规排除输尿管结石",
                "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.dxd_urolith",
                "title": "提出输尿管结石并说明排除依据",
                "reason": "本轮评分未找到足够证据，建议复习该临床推理要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.dxd_crohn",
                "title": "提出克罗恩病并说明排除依据",
                "reason": "本轮评分未找到足够证据，建议复习该临床推理要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.dxd_ectopic",
                "title": "考虑异位妊娠并正确排除",
                "reason": "本轮评分未找到足够证据，建议复习该临床推理要点。",
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.rs_exclude",
                "title": "推理表达覆盖关键排除依据",
                "reason": "本轮评分未找到足够证据，建议复习该临床推理要点。",
            },
            {
                "reference": "case:acs_001",
                "title": "胸痛伴出汗教学病例",
                "reason": "病例库暂无同模块病例，推荐用于下一轮对照训练。",
            },
            {
                "reference": "case:heart_failure_001",
                "title": "活动后气短伴夜间憋醒教学病例",
                "reason": "病例库暂无同模块病例，推荐用于下一轮对照训练。",
            },
        ],
    }
