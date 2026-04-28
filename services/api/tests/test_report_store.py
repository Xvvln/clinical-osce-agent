from app.services.report_store import ReportStore


def test_report_store_persists_report_across_instances(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    report = {
        "report_id": "session_demo_report",
        "session_id": "session_demo",
        "case_id": "appendicitis_001",
        "total_score": 55,
        "feedback_summary": "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。",
    }

    ReportStore(database_path).save_report(report)
    loaded_report = ReportStore(database_path).get_report("session_demo")

    assert loaded_report == report
