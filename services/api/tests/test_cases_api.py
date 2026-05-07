from fastapi.testclient import TestClient

from app import main
from app.services.auth_store import AuthStore


client = TestClient(main.app)


def _expected_appendicitis_auxiliary_quick_options() -> list[dict[str, object]]:
    return [
        {
            "test_code": "lab.cbc",
            "test_name_cn": "血常规",
            "category": "实验室",
            "invasiveness": "微创",
            "cost_hint": "基础",
            "diagnostic_role": "supports_primary_diagnosis",
            "rules_out": [],
            "recommended_stage": "auxiliary_test",
            "overuse_warning": None,
        },
        {
            "test_code": "lab.crp",
            "test_name_cn": "C 反应蛋白",
            "category": "实验室",
            "invasiveness": "微创",
            "cost_hint": "基础",
            "diagnostic_role": "supports_primary_diagnosis",
            "rules_out": [],
            "recommended_stage": "auxiliary_test",
            "overuse_warning": None,
        },
        {
            "test_code": "img.abd_us",
            "test_name_cn": "腹部超声",
            "category": "影像",
            "invasiveness": "无创",
            "cost_hint": "基础",
            "diagnostic_role": "supports_primary_diagnosis",
            "rules_out": [],
            "recommended_stage": "auxiliary_test",
            "overuse_warning": None,
        },
        {
            "test_code": "lab.urinalysis",
            "test_name_cn": "尿常规",
            "category": "实验室",
            "invasiveness": "无创",
            "cost_hint": "基础",
            "diagnostic_role": "rules_out_alternative",
            "rules_out": ["右侧输尿管结石"],
            "recommended_stage": "auxiliary_test",
            "overuse_warning": None,
        },
        {
            "test_code": "img.abd_ct",
            "test_name_cn": "腹部 CT",
            "category": "影像",
            "invasiveness": "无创",
            "cost_hint": "中等",
            "diagnostic_role": "supports_primary_diagnosis",
            "rules_out": [],
            "recommended_stage": "auxiliary_test",
            "overuse_warning": "基础病史、查体、血常规和超声已足够支持训练推理时，不应把 CT 作为第一步机械申请。",
        },
    ]


def test_list_cases_returns_valid_case_summaries() -> None:
    response = client.get("/api/cases")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"cases"}
    case_ids = [case_summary["case_id"] for case_summary in payload["cases"]]
    assert case_ids == [
        "acs_001",
        "appendicitis_001",
        "heart_failure_001",
        "hyperthyroid_001",
        "pneumonia_001",
    ]
    appendicitis_case = next(case_summary for case_summary in payload["cases"] if case_summary["case_id"] == "appendicitis_001")
    assert appendicitis_case == {
        "case_id": "appendicitis_001",
        "case_title": "右下腹痛教学病例",
        "course_module": "腹痛",
        "difficulty": "初级",
        "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
        "enabled": True,
        "patient_profile": {
            "age": "22岁",
            "gender": "男",
            "occupation": "学生",
            "hospital_department": "急诊外科",
        },
        "opening_task_card": {
            "role": "你是急诊外科接诊医生。",
            "scenario": "一名22岁男性学生因转移性右下腹痛 24 小时，伴恶心、低热来诊。",
            "tasks": [
                "进行有重点的病史采集",
                "判断需要哪些查体",
                "选择必要辅助检查",
                "提出诊断假设和鉴别诊断",
                "最终提交诊断与推理依据",
            ],
        },
        "physical_exam_options": [
            {"exam_code": "vital.temperature", "exam_name_cn": "体温"},
            {"exam_code": "abd.inspection", "exam_name_cn": "腹部视诊"},
            {"exam_code": "abd.palpation.tenderness", "exam_name_cn": "McBurney 点压痛"},
            {"exam_code": "abd.palpation.rebound", "exam_name_cn": "反跳痛（Blumberg 征）"},
            {"exam_code": "abd.palpation.guarding", "exam_name_cn": "肌紧张"},
            {"exam_code": "abd.special.rovsing", "exam_name_cn": "Rovsing 征"},
            {"exam_code": "abd.special.psoas", "exam_name_cn": "腰大肌征"},
        ],
        "auxiliary_test_options": _expected_appendicitis_auxiliary_quick_options(),
        "teaching_focus": {
            "learning_objectives": [
                "围绕急腹症完成疼痛演变史采集",
                "选择关键腹部查体验证右下腹体征",
                "用基础实验室和影像检查支持或修正诊断假设",
                "表达阳性证据与鉴别排除依据",
            ],
            "common_error_patterns": [
                {
                    "pattern_id": "appendicitis_001.pattern.history_migration_gap",
                    "title": "腹痛演变史采集不足",
                    "focus": "只问当前疼痛部位，漏掉起病部位、转移过程和诱发加重因素。",
                    "related_rubric_items": ["ht_onset", "ht_migration", "ht_character"],
                },
                {
                    "pattern_id": "appendicitis_001.pattern.peritoneal_exam_gap",
                    "title": "腹膜刺激征检查不足",
                    "focus": "完成一般查体后，没有继续验证右下腹压痛、反跳痛和局部肌紧张。",
                    "related_rubric_items": ["pe_tenderness", "pe_rebound"],
                },
                {
                    "pattern_id": "appendicitis_001.pattern.reasoning_chain_gap",
                    "title": "证据链表达不足",
                    "focus": "诊断假设较早出现，但没有把病史、查体、检查和鉴别排除串成完整推理。",
                    "related_rubric_items": ["rs_support", "rs_exclude", "dxd_urolith"],
                },
            ],
            "recommended_training_path": [
                "先完成起病、部位变化、性质、程度和伴随症状问诊",
                "再选择体温、腹部视诊、右下腹压痛和反跳痛等关键查体",
                "随后用血常规、CRP、腹部超声和尿常规验证诊断假设与鉴别排除",
                "最后提交诊断、支持证据、排除依据和下一步训练方向",
            ],
        },
    }
    assert "result" not in str(appendicitis_case["physical_exam_options"])
    assert "result" not in str(appendicitis_case["auxiliary_test_options"])
    assert "急性阑尾炎" not in str(appendicitis_case)


def test_get_case_detail_returns_student_safe_payload() -> None:
    response = client.get("/api/cases/appendicitis_001")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"case"}
    case_payload = payload["case"]
    assert case_payload["case_id"] == "appendicitis_001"
    assert case_payload["case_title"] == "右下腹痛教学病例"
    assert case_payload["course_module"] == "腹痛"
    assert case_payload["difficulty"] == "初级"
    assert case_payload["chief_complaint"] == "转移性右下腹痛 24 小时，伴恶心、低热"
    assert case_payload["patient_profile"] == {
        "age": "22岁",
        "gender": "男",
        "occupation": "学生",
        "hospital_department": "急诊外科",
    }
    assert case_payload["opening_task_card"]["tasks"] == [
        "进行有重点的病史采集",
        "判断需要哪些查体",
        "选择必要辅助检查",
        "提出诊断假设和鉴别诊断",
        "最终提交诊断与推理依据",
    ]
    assert case_payload["teaching_focus"]["learning_objectives"][0] == "围绕急腹症完成疼痛演变史采集"
    assert case_payload["teaching_focus"]["common_error_patterns"][0] == {
        "pattern_id": "appendicitis_001.pattern.history_migration_gap",
        "title": "腹痛演变史采集不足",
        "focus": "只问当前疼痛部位，漏掉起病部位、转移过程和诱发加重因素。",
        "related_rubric_items": ["ht_onset", "ht_migration", "ht_character"],
    }
    assert case_payload["teaching_focus"]["recommended_training_path"][-1] == "最后提交诊断、支持证据、排除依据和下一步训练方向"
    assert case_payload["physical_exam_options"][0] == {"exam_code": "vital.temperature", "exam_name_cn": "体温"}
    assert case_payload["auxiliary_test_options"] == _expected_appendicitis_auxiliary_quick_options()
    assert "hidden_facts" not in str(case_payload)
    assert "canonical_answer" not in str(case_payload)
    assert "result" not in str(case_payload["physical_exam_options"])
    assert "result" not in str(case_payload["auxiliary_test_options"])
    assert "急性阑尾炎" not in str(case_payload)


def test_get_case_detail_returns_404_for_unknown_case() -> None:
    response = client.get("/api/cases/not_found_001")

    assert response.status_code == 404
    assert response.json() == {"detail": "case not found"}


def test_get_case_raw_requires_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as unauthenticated_client:
        response = unauthenticated_client.get("/api/cases/appendicitis_001/raw")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_get_case_raw_rejects_non_admin_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@example.test")
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as non_admin_client:
        register_response = non_admin_client.post(
            "/api/auth/register",
            json={"email": "student@example.test", "password": "safe-student-password", "display_name": "学生"},
        )
        assert register_response.status_code == 200
        response = non_admin_client.get("/api/cases/appendicitis_001/raw")

    assert response.status_code == 403
    assert response.json() == {"detail": "admin access required"}


def test_get_case_raw_returns_complete_case_payload_for_admin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@example.test")
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as admin_client:
        register_response = admin_client.post(
            "/api/auth/register",
            json={"email": "admin@example.test", "password": "safe-admin-password", "display_name": "管理员"},
        )
        assert register_response.status_code == 200
        response = admin_client.get("/api/cases/appendicitis_001/raw")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"case"}
    case_payload = payload["case"]
    assert case_payload["case_id"] == "appendicitis_001"
    assert case_payload["chief_complaint"] == "转移性右下腹痛 24 小时，伴恶心、低热"
    assert case_payload["history"]["present_illness_summary"] == "患者 24 小时前无明显诱因出现上腹部隐痛，伴恶心，未呕吐，约 8 小时前疼痛转移并固定于右下腹，程度较前加重，行走时加重，伴低热。"
    assert len(case_payload["history"]["hidden_facts"]) == 10
    assert case_payload["history"]["hidden_facts"][0]["canonical_answer"] == "24 小时前开始，最初是上腹部隐痛。"
    assert case_payload["physical_exam"]["must_items"][0]["exam_code"] == "vital.temperature"
    assert case_payload["auxiliary_tests"]["must_items"][0]["test_code"] == "lab.cbc"
    assert case_payload["diagnosis"]["reasoning_points"][0]["point_id"] == "appendicitis_001.rp_01"
    assert case_payload["source_attribution"]["source_id"] == "fareez_osce_2022"
