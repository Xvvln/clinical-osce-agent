from app.services.source_retriever import retrieve_feedback_source_items


def test_retrieve_feedback_source_items_returns_indexed_case_source_and_evidence() -> None:
    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {
            "ht_migration": {"score": 0},
            "dx_main": {"score": 15},
        },
        "missed_items": ["ht_migration"],
        "dimension_traces": {
            "physical_exam": [
                {
                    "rubric_item_id": "pe_rebound",
                    "match_kind": "exam_code",
                    "matched_evidence": ["abd.palpation.rebound"],
                }
            ],
            "main_diagnosis": [
                {
                    "rubric_item_id": "dx_main",
                    "match_kind": "diagnosis_concept",
                    "matched_evidence": ["急性阑尾炎"],
                }
            ],
        },
    }

    items = retrieve_feedback_source_items(report, ["appendicitis_001.hf_01"])

    assert [item.reference for item in items] == [
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "evidence:appendicitis_001.hf_01",
        "evidence:abd.palpation.rebound",
        "evidence:急性阑尾炎",
    ]
    assert items[0].title == "右下腹痛教学病例"
    assert items[0].source_type == "case"
    assert items[1].title == "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases"
    assert items[1].source_type == "source"
    assert items[1].metadata["license"] == "CC BY 4.0"
    assert items[2].title == "追问疼痛部位及转移特征"
    assert items[2].source_type == "rubric"
    assert items[3].title == "24 小时前开始，最初是上腹部隐痛。"
    assert items[3].source_type == "evidence"
    assert items[4].title == "右下腹反跳痛阳性。"
    assert items[4].source_type == "evidence"
    assert items[5].title == "急性阑尾炎"
    assert items[5].source_type == "evidence"


def test_retrieve_feedback_sources_keeps_stable_reference_contract() -> None:
    from app.services.source_retriever import retrieve_feedback_sources

    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {"ht_migration": {"score": 0}},
        "missed_items": ["ht_migration"],
        "dimension_traces": {},
    }

    assert retrieve_feedback_sources(report, ["appendicitis_001.hf_01"]) == [
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "evidence:appendicitis_001.hf_01",
    ]
