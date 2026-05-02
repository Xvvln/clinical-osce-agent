from app.services.training_skill_candidate_service import (
    TrainingSkillCandidateContext,
    TrainingSkillCandidateService,
)


def test_training_skill_candidate_service_uses_injected_generator_for_high_frequency_items() -> None:
    captured_contexts: list[TrainingSkillCandidateContext] = []

    class FakeTrainingSkillCandidateGenerator:
        def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, object]:
            captured_contexts.append(context)
            return {
                "candidate_id": f"llm_candidate_{context.item_id}",
                "trigger_item_id": context.item_id,
                "title": "LLM 生成的推理训练 Skill",
                "description": f"LLM 基于 {context.support_count} 次漏项生成。",
                "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
                "status": "draft",
                "source_report_count": context.source_report_count,
                "support_count": context.support_count,
                "related_recommendations": context.related_recommendations,
            }

    insights = {
        "session_count": 3,
        "report_count": 3,
        "frequent_missed_items": [
            {
                "item_id": "reasoning_core",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
            },
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 2,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
    }

    candidates = TrainingSkillCandidateService(
        generator=FakeTrainingSkillCandidateGenerator(),
    ).propose_candidates(insights, min_count=2)

    assert captured_contexts == [
        TrainingSkillCandidateContext(
            item_id="reasoning_core",
            support_count=2,
            case_ids=["appendicitis_001", "pneumonia_001"],
            source_report_count=3,
            related_recommendations=[
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        )
    ]
    assert candidates == [
        {
            "candidate_id": "llm_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "LLM 生成的推理训练 Skill",
            "description": "LLM 基于 2 次漏项生成。",
            "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_training_skill_candidate_service_proposes_reasoning_candidate_from_frequent_missed_item() -> None:
    insights = {
        "session_count": 3,
        "report_count": 3,
        "frequent_missed_items": [
            {
                "item_id": "reasoning_core",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
            },
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 2,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
    }

    candidates = TrainingSkillCandidateService().propose_candidates(insights, min_count=2)

    assert candidates == [
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_training_skill_candidate_service_skips_low_frequency_missed_items() -> None:
    insights = {
        "session_count": 1,
        "report_count": 1,
        "frequent_missed_items": [
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            }
        ],
        "frequent_learning_recommendations": [],
    }

    candidates = TrainingSkillCandidateService().propose_candidates(insights, min_count=2)

    assert candidates == []
