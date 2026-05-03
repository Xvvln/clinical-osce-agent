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


def test_report_store_lists_reports_newest_first(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    first_report = {
        "report_id": "report_first",
        "session_id": "session_first",
        "case_id": "appendicitis_001",
        "student_id": "student_first",
        "total_score": 72,
    }
    second_report = {
        "report_id": "report_second",
        "session_id": "session_second",
        "case_id": "appendicitis_002",
        "student_id": "student_second",
        "total_score": 86,
    }

    store = ReportStore(database_path)
    store.save_report(first_report)
    store.save_report(second_report)

    assert ReportStore(database_path).list_reports() == [second_report, first_report]
