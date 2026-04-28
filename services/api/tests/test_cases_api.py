from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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
    }


def test_get_case_raw_returns_complete_case_payload() -> None:
    response = client.get("/api/cases/appendicitis_001/raw")

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
