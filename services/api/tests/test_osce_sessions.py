from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_osce_session_minimal_training_loop() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session_id"]
    assert created["case_id"] == "appendicitis_001"
    assert created["student_id"] == "student_demo"
    assert created["stage"] == "case_intro"
    assert created["case_title"] == "右下腹痛教学病例"
    assert created["chief_complaint"] == "转移性右下腹痛 24 小时，伴恶心、低热"

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
    assert test_payload["result"] == "白细胞升高，中性粒细胞比例升高。"
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
    assert report_payload["total_score"] == 55
    assert report_payload["dimension_scores"] == {
        "history_taking": 10,
        "physical_exam": 15,
        "auxiliary_test": 15,
        "main_diagnosis": 15,
        "differential_diagnosis": 0,
        "reasoning": 0,
    }
    assert report_payload["rubric_scores"]["ht_onset"]["score"] == 10
    assert report_payload["rubric_scores"]["ht_location"]["score"] == 0
    assert report_payload["rubric_scores"]["pe_rebound"]["score"] == 15
    assert report_payload["rubric_scores"]["at_cbc"]["score"] == 15
    assert report_payload["rubric_scores"]["dx_appendicitis"]["score"] == 15
    assert "ht_location" in report_payload["missed_items"]
    assert report_payload["strengths"] == [
        "追问起病时间：已完成。",
        "请求右下腹反跳痛检查：已完成。",
        "请求血常规：已完成。",
        "主诊断命中急性阑尾炎：已完成。",
    ]
    assert report_payload["reasoning_errors"] == [
        "鉴别诊断覆盖常见右下腹痛病因且表述合理：评分轨迹未找到足够证据。",
        "推理链覆盖关键证据并能自圆其说：评分轨迹未找到足够证据。",
    ]
    assert report_payload["next_recommendations"] == [
        "下一轮训练重点：追问疼痛部位与转移。",
        "下一轮训练重点：鉴别诊断覆盖常见右下腹痛病因且表述合理。",
        "下一轮训练重点：推理链覆盖关键证据并能自圆其说。",
    ]
    assert report_payload["source_references"] == [
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_location",
        "rubric:appendicitis_001_rubric.item.dd_reasonable",
        "rubric:appendicitis_001_rubric.item.reasoning_core",
        "evidence:appendicitis_001.hf_01",
        "evidence:abd.palpation.rebound",
        "evidence:lab.cbc",
        "evidence:急性阑尾炎",
    ]
    assert report_payload["feedback_summary"] == "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。"
    report_text = str(report_payload)
    for forbidden_term in ["用药剂量", "治疗方案", "手术方案", "处置建议"]:
        assert forbidden_term not in report_text
