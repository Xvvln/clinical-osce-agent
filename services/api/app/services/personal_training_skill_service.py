from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from app.models.case import Case
from app.services.admin_display_resolver import rubric_item_labels
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_auto_approval_service import AUTO_APPROVAL_AGENT_ID, TrainingSkillApprovalAgent
from app.services.training_skill_candidate_service import (
    TrainingSkillCandidateContext,
    TrainingSkillCandidateGenerator,
    TrainingSkillCandidateMissedItem,
    create_default_training_skill_candidate_generator,
)
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_regression_gate import TrainingSkillRegressionGate
from app.services.training_skill_store import TrainingSkillStore

MAX_APPROVAL_AGENT_ROUNDS = 3
TEACHER_REFLECTION_PROMPT_VERSION = "teacher_reflection_v2"

TEACHER_REFLECTION_PROMPT_CONTRACT = """你是 OSCE 训练报告里的教师复盘 Agent。

你的读者是刚完成一次训练的学生。你的任务不是证明系统评分正确，也不是展示 RAG 来源或 Skill 内部记录，
而是用老师讲评的口吻帮助学生理解：本轮哪里做得好、哪里没做好、为什么会影响临床推理、正确顺序是什么、下一轮怎么练。

硬性规则：
- 只能基于后端提供的病例标题、rubric 中文训练点、已覆盖/未覆盖线索、维度得分和学生提交内容讲评。
- 不得新增病例事实、修改标准诊断、改写 rubric 或泄露隐藏材料。
- 不得输出真实诊疗建议、治疗方案、用药剂量或处置指令。
- 不要机械罗列每个 missed_item；必须把漏项归纳成 2-4 个临床思维问题组。
- 每个问题组必须包含：学生本轮表现、为什么重要、正确做法、下一轮具体练习动作。
- 用老师对学生说话的语气，明确、具体、可执行，避免“加强学习”这类空话。
- 如果学生已经覆盖较完整，重点转为证据表达、支持/排除依据和迁移训练。
- 输出结构化 JSON：overall_comment、strengths_review、major_issues、reasoning_chain_review、next_practice_plan、teacher_note。
"""

ISSUE_GROUP_PRIORITY = ["history", "physical_exam", "auxiliary_test", "reasoning"]

ISSUE_GROUP_DEFINITIONS: dict[str, dict[str, str]] = {
    "history": {
        "title": "病史时间线与症状结构不完整",
        "observed": "本轮病史采集还没有把起病、部位变化、疼痛性质、程度和伴随症状完整串起来。",
        "why": "急腹症判断首先依赖疼痛演变和伴随表现；缺少这条时间线，即使最终诊断方向接近，证据链也不够稳。",
        "correct": "先围绕起病时间、最初部位、是否转移、性质、程度、恶心呕吐发热腹泻尿痛等问题建立完整病史框架。",
        "next": "下一轮先完成腹痛六问，再进入查体或检查申请。",
    },
    "physical_exam": {
        "title": "查体没有围绕诊断假设补足关键体征",
        "observed": "本轮查体选择没有充分覆盖能验证腹部局部体征和腹膜刺激征的关键环节。",
        "why": "查体是把主诉和诊断假设连接起来的中间证据；缺少关键体征会让后续检查和诊断表达显得跳跃。",
        "correct": "在完成基本病史后，按一般状态、腹部视诊、局部压痛、反跳痛、肌紧张和相关诱发体征逐步验证。",
        "next": "下一轮在申请检查前，先补足与当前假设直接相关的腹部查体。",
    },
    "auxiliary_test": {
        "title": "辅助检查没有形成支持与排除证据",
        "observed": "本轮辅助检查申请还没有完整覆盖基础炎症指标、尿路相关排除或必要影像证据。",
        "why": "辅助检查不是为了堆项目，而是为了支持主要诊断、修正风险判断，并排除容易混淆的鉴别诊断。",
        "correct": "根据病史和查体结果选择血常规/炎症指标、尿常规和必要影像，并说明每项检查要验证什么。",
        "next": "下一轮每申请一个检查，都补一句它支持什么或排除什么。",
    },
    "reasoning": {
        "title": "鉴别诊断和证据表达没有闭环",
        "observed": "本轮推理表达还没有把阳性依据、阴性依据和鉴别排除依据组织成完整链条。",
        "why": "OSCE 不只看最终诊断名称，更看你是否能说明为什么支持它、为什么暂不支持其他可能。",
        "correct": "提交前按“支持依据、反证/排除依据、仍需验证的问题”组织诊断推理。",
        "next": "下一轮提交诊断前，先口头整理至少两条支持依据和一条排除依据。",
    },
}

HISTORY_SLOT_TRAINING_LABELS = {
    "onset": "追问起病时间",
    "duration": "追问持续时间",
    "location": "追问疼痛部位",
    "character": "追问疼痛性质",
    "radiation": "追问放射或转移",
    "severity": "追问疼痛程度",
    "aggravating": "追问加重因素",
    "relieving": "追问缓解因素",
    "progression": "追问症状演变",
    "associated_symptom": "追问伴随症状",
    "frequency": "追问发作频率",
    "timing": "追问发作时段",
    "context": "追问诱发背景",
    "negation": "追问阴性症状",
}


def build_not_ready_personal_skill_payload() -> dict[str, Any]:
    return {
        "personal_skill_candidate": {
            "status": "not_complete",
            "reason": "final_submission_required",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
        },
        "ai_reflection_review": {
            "status": "not_ready",
            "reason": "final_submission_required",
            "summary": "提交诊断并生成完整评分报告后，系统会生成教师复盘和下一轮个人训练 Skill。",
            "mistake_patterns": [],
            "teacher_feedback": "",
            "next_focus": "",
            "source_references": [],
            "source_reference_items": [],
        },
    }


def build_generation_failed_personal_skill_payload(*, report: dict[str, Any], case: Case) -> dict[str, Any]:
    return {
        "personal_skill_candidate": {
            "status": "generation_failed",
            "reason": "skill_candidate_generation_failed",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
            "summary": "个人训练 Skill 暂未生成；请检查当前账号的模型服务配置后重试打开报告。",
        },
        "ai_reflection_review": _build_ai_reflection_review(report, case),
    }


class PersonalTrainingSkillService:
    def __init__(
        self,
        *,
        generator: TrainingSkillCandidateGenerator | None = None,
        approval_agent: TrainingSkillApprovalAgent | None = None,
        regression_gate: TrainingSkillRegressionGate | None = None,
    ) -> None:
        self._generator = generator or create_default_training_skill_candidate_generator()
        self._approval_agent = approval_agent or TrainingSkillApprovalAgent()
        self._regression_gate = regression_gate or TrainingSkillRegressionGate()

    def generate_for_completed_session(
        self,
        *,
        session: Any,
        case: Case,
        report: dict[str, Any],
        candidate_store: TrainingSkillCandidateStore,
        skill_store: TrainingSkillStore,
        event_store: TrainingEventStore,
    ) -> dict[str, Any]:
        candidate_id = _personal_candidate_id(str(session.session_id))
        existing_candidate = candidate_store.get_candidate(candidate_id)
        if existing_candidate is not None:
            return {
                "personal_skill_candidate": _report_candidate_summary(existing_candidate),
                "ai_reflection_review": _build_ai_reflection_review(report, case),
            }

        candidate = self._generate_candidate(session=session, case=case, report=report)
        candidate, review, approval_dialogue = self._review_candidate(candidate, case)
        candidate["approval_dialogue"] = approval_dialogue
        candidate["review"] = review
        candidate_store.save_candidate(candidate, review)
        if review["status"] == "approved":
            skill_store.enable_candidate(candidate)

        skill_id = _personal_skill_id(str(session.session_id))
        _append_personal_skill_events(
            candidate=candidate,
            review=review,
            event_store=event_store,
            session=session,
            skill_id=skill_id,
        )
        return {
            "personal_skill_candidate": _report_candidate_summary(candidate),
            "ai_reflection_review": _build_ai_reflection_review(report, case),
        }

    def _generate_candidate(self, *, session: Any, case: Case, report: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session.session_id)
        report_id = str(report.get("report_id") or f"{session_id}_report")
        missed_items = _missed_items_from_report(report, case.case_id)
        context = TrainingSkillCandidateContext(
            pattern_id=f"personal_{session_id}",
            missed_items=missed_items,
            support_count=1,
            case_ids=[case.case_id],
            source_report_count=1,
            related_recommendations=_related_recommendations(report),
        )
        candidate = self._generator.generate_candidate(context)
        trigger_item_ids = [item.item_id for item in missed_items] or ["reflection:structured_expression"]
        stage_scope = ["case_intro", "history_taking", "physical_exam", "auxiliary_testing", "diagnosis_submission"]
        candidate.update(
            {
                "candidate_id": _personal_candidate_id(session_id),
                "trigger_item_id": f"personal_{session_id}",
                "trigger_item_ids": trigger_item_ids,
                "case_ids": [case.case_id],
                "scope": "personal",
                "owner_student_id": str(session.student_id),
                "source_session_id": session_id,
                "source_session_ids": [session_id],
                "source_report_ids": [report_id],
                "source_report_count": 1,
                "support_count": 1,
                "stage_scope": stage_scope,
                "effect_status": "insufficient_samples",
                "applies_when": {
                    "case_ids": [case.case_id],
                    "stage_scope": stage_scope,
                    "trigger_item_ids": trigger_item_ids,
                    "current_missing_evidence": trigger_item_ids,
                    "min_support_count": 1,
                    "owner_student_id": str(session.student_id),
                    "source_session_id": session_id,
                },
                "rag_evidence_items": _rag_evidence_items(report),
                "web_check_status": "not_configured",
                "external_evidence_checks": [],
            }
        )
        if candidate.get("title") == "OSCE 训练模式纠偏提示":
            candidate["title"] = "个人复盘训练 Skill"
        return candidate

    def _review_candidate(self, candidate: dict[str, Any], case: Case) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        current_candidate = deepcopy(candidate)
        approval_dialogue: list[dict[str, Any]] = []
        protected_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
        review: dict[str, Any] = {}
        for round_index in range(1, MAX_APPROVAL_AGENT_ROUNDS + 1):
            reviewed_candidate = self._approval_agent.review_candidate(
                current_candidate,
                protected_terms=protected_terms,
            )
            review = self._regression_gate.review_candidate(reviewed_candidate, _passing_batch_result())
            approved = review["status"] == "ready_for_review"
            agent_review = reviewed_candidate.get("approval_agent_review", {})
            approval_dialogue.append(
                {
                    "round": round_index,
                    "agent_id": AUTO_APPROVAL_AGENT_ID,
                    "decision": "approved" if approved else "revise",
                    "revision_status": agent_review.get("revision_status", "unchanged"),
                    "changed_fields": list(agent_review.get("changed_fields", [])),
                    "rag_reference_count": len(reviewed_candidate.get("rag_evidence_items", [])),
                    "web_check_status": reviewed_candidate.get("web_check_status", "not_configured"),
                    "blocking_failures": list(review.get("blocking_failures", [])),
                    "candidate_safety_violations": list(review.get("candidate_safety_violations", [])),
                    "candidate_context_violations": list(review.get("candidate_context_violations", [])),
                }
            )
            current_candidate = reviewed_candidate
            if approved:
                return current_candidate, {
                    **review,
                    "status": "approved",
                    "reviewer_id": AUTO_APPROVAL_AGENT_ID,
                    "approval_mode": "auto_agent_personal",
                }, approval_dialogue
        return current_candidate, {
            **review,
            "status": "blocked_by_regression",
            "reviewer_id": AUTO_APPROVAL_AGENT_ID,
            "approval_mode": "auto_agent_personal",
        }, approval_dialogue


def _passing_batch_result() -> Any:
    return SimpleNamespace(
        total_cases=0,
        passed_cases=0,
        failed_cases=0,
        results=[],
        passed=True,
        total_duration_ms=0,
    )


def _missed_items_from_report(report: dict[str, Any], case_id: str) -> list[TrainingSkillCandidateMissedItem]:
    missed_items = [str(item_id) for item_id in report.get("missed_items", []) if str(item_id)]
    if not missed_items:
        missed_items = ["reflection:structured_expression"]
    return [
        TrainingSkillCandidateMissedItem(
            item_id=item_id,
            count=1,
            case_ids=[case_id],
        )
        for item_id in missed_items[:8]
    ]


def _related_recommendations(report: dict[str, Any]) -> list[str]:
    references = [
        str(recommendation.get("reference"))
        for recommendation in report.get("knowledge_recommendations", [])
        if isinstance(recommendation, dict) and recommendation.get("reference")
    ]
    if references:
        return references
    return [str(reference) for reference in report.get("source_references", [])[:8]]


def _rag_evidence_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    source_items = report.get("source_reference_items", [])
    if not isinstance(source_items, list):
        return []
    return [
        {
            "reference": str(item.get("reference", "")),
            "source_type": str(item.get("source_type", "")),
            "title": str(item.get("title", "")),
            "metadata": item.get("metadata", {}),
        }
        for item in source_items
        if isinstance(item, dict) and item.get("reference")
    ][:12]


def build_teacher_reflection_review_payload(report: dict[str, Any], case: Case | None = None) -> dict[str, Any]:
    return _build_ai_reflection_review(report, case)


def _build_ai_reflection_review(report: dict[str, Any], case: Case | None = None) -> dict[str, Any]:
    missed_items = [str(item_id) for item_id in report.get("missed_items", [])]
    case_id = str(report.get("case_id") or getattr(case, "case_id", "") or "")
    case_title = str(getattr(case, "case_title", "") or case_id or "当前病例")
    missed_labels = rubric_item_labels(missed_items[:8], [case_id]) if missed_items else []
    covered_labels = _coverage_map_labels(report, "covered", limit=4, case=case)
    pending_labels = _coverage_map_labels(report, "pending", limit=4, case=case)
    source_reference_items = _rag_evidence_items(report)
    source_references = [item["reference"] for item in source_reference_items]
    score_text = _score_text(report)
    strengths_review = _build_strengths_review(report, covered_labels)
    major_issues = _build_teacher_major_issues(
        report=report,
        case=case,
        case_id=case_id,
        missed_items=missed_items,
        missed_labels=missed_labels,
        pending_labels=pending_labels,
    )
    overall_comment = _build_overall_teacher_comment(
        case_title=case_title,
        score_text=score_text,
        missed_items=missed_items,
        major_issues=major_issues,
    )
    reasoning_chain_review = _build_reasoning_chain_review(case_title=case_title, major_issues=major_issues)
    next_practice_plan = _build_next_practice_plan(major_issues, pending_labels)
    teacher_note = (
        "复盘时先看问题背后的推理顺序：先把病史问完整，再用查体和检查验证假设，最后用证据说明支持与排除。"
    )
    if missed_items:
        summary = (
            f"本轮病例「{case_title}」得到 {score_text}；主诊断方向已建立，但仍有 {len(missed_items)} "
            f"个训练点需要复盘，重点是{_compact_list_text(missed_labels, limit=3, fallback='本轮未覆盖的关键评分点')}。"
        )
        teacher_feedback = (
            "从老师视角看，本轮不是单个知识点问题，而是病例评估链条还不够闭合。"
            f"你已经覆盖了{_compact_list_text(covered_labels, limit=4, fallback='部分关键证据')}，这些能支撑主要判断；"
            f"但{_compact_list_text(missed_labels, limit=4, fallback='本轮未覆盖的关键评分点')}没有充分呈现，"
            "会让鉴别诊断和排除依据显得不稳。为什么要补这些：OSCE 评分看的是能否把病史、查体、检查和鉴别排除串成证据链，"
            "而不只是写出可能诊断。"
        )
    else:
        summary = f"本轮病例「{case_title}」得到 {score_text}；核心评分项覆盖较完整，复盘重点转为表达结构和迁移训练。"
        teacher_feedback = (
            f"从老师视角看，本轮对「{case_title}」的主要证据链比较完整。"
            "下一步要把每个阳性和阴性依据说清楚：它支持什么、排除了什么、还有什么不确定。"
            "为什么要这样做：临床推理评价关注证据与结论之间的关系，而不是只看最终诊断名称。"
        )
    if pending_labels:
        next_focus = (
            "下一轮先按“病史补全 → 关键查体 → 必要检查 → 鉴别排除”的顺序练习，"
            f"优先补{_compact_list_text(pending_labels, limit=4, fallback='未覆盖的关键线索')}，并说明每一步为什么会改变判断。"
        )
    else:
        next_focus = "下一轮继续练习把已收集证据整理成支持依据、反证依据和仍需验证的问题。"
    return {
        "status": "generated",
        "summary": summary,
        "overall_comment": overall_comment,
        "strengths_review": strengths_review,
        "major_issues": major_issues,
        "reasoning_chain_review": reasoning_chain_review,
        "next_practice_plan": next_practice_plan,
        "teacher_note": teacher_note,
        "mistake_patterns": missed_items[:8],
        "teacher_feedback": teacher_feedback,
        "next_focus": next_focus,
        "source_references": source_references,
        "source_reference_items": source_reference_items,
        "generated_by": "teacher_reflection_agent",
        "teaching_prompt_version": TEACHER_REFLECTION_PROMPT_VERSION,
        "safety_note": "本轮教师复盘仅用于 OSCE 教学训练，不改变病例事实、rubric、标准诊断或评分规则。",
    }


def _build_overall_teacher_comment(
    *,
    case_title: str,
    score_text: str,
    missed_items: list[str],
    major_issues: list[dict[str, Any]],
) -> str:
    if missed_items:
        issue_titles = [str(issue.get("title", "")) for issue in major_issues[:2] if issue.get("title")]
        issue_text = _compact_list_text(issue_titles, limit=2, fallback="证据采集和推理表达")
        return (
            f"这次「{case_title}」得到 {score_text}。你已经进入主要诊断方向，但证据链还没有闭合，"
            f"核心问题集中在{issue_text}。"
        )
    return (
        f"这次「{case_title}」得到 {score_text}。核心证据链比较完整，后续重点是把支持依据、"
        "排除依据和仍需验证的问题表达得更清楚。"
    )


def _build_strengths_review(report: dict[str, Any], covered_labels: list[str]) -> list[str]:
    strengths = [str(item).strip() for item in report.get("strengths", []) if str(item).strip()]
    if strengths:
        return strengths[:3]
    if covered_labels:
        return [f"你已经覆盖了{_compact_list_text(covered_labels, limit=3, fallback='部分关键线索')}，说明问诊或检查方向已有基础。"]
    return ["你完成了病例训练并提交了诊断，后续可以在证据链组织上继续提升。"]


def _build_teacher_major_issues(
    *,
    report: dict[str, Any],
    case: Case | None,
    case_id: str,
    missed_items: list[str],
    missed_labels: list[str],
    pending_labels: list[str],
) -> list[dict[str, Any]]:
    grouped_items = _group_teacher_issue_items(missed_items, missed_labels, case_id)
    pending_by_group = _coverage_map_labels_by_group(report, "pending", limit_per_group=4, case=case)
    issues: list[dict[str, Any]] = []
    for group in ISSUE_GROUP_PRIORITY:
        linked_items = [*grouped_items.get(group, []), *pending_by_group.get(group, [])]
        linked_items = _dedupe_texts(linked_items)[:6]
        if not linked_items:
            continue
        definition = ISSUE_GROUP_DEFINITIONS[group]
        issues.append(
            {
                "title": definition["title"],
                "observed_behavior": f"{definition['observed']} 本轮相关训练点包括：{_compact_list_text(linked_items, limit=4, fallback='关键训练点')}。",
                "why_it_matters": definition["why"],
                "correct_approach": definition["correct"],
                "next_action": definition["next"],
                "linked_items": linked_items,
            }
        )
        if len(issues) >= 4:
            break
    if issues:
        return issues
    return [
        {
            "title": "证据表达还可以继续精炼",
            "observed_behavior": "本轮关键采集较完整，主要提升点是把已获得信息整理成更清楚的支持与排除依据。",
            "why_it_matters": ISSUE_GROUP_DEFINITIONS["reasoning"]["why"],
            "correct_approach": ISSUE_GROUP_DEFINITIONS["reasoning"]["correct"],
            "next_action": ISSUE_GROUP_DEFINITIONS["reasoning"]["next"],
            "linked_items": [],
        }
    ]


def _group_teacher_issue_items(missed_items: list[str], missed_labels: list[str], case_id: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {group: [] for group in ISSUE_GROUP_PRIORITY}
    for index, item_id in enumerate(missed_items[:8]):
        label = missed_labels[index] if index < len(missed_labels) and missed_labels[index] else item_id
        group = _teacher_issue_group_for_item(item_id)
        if label not in grouped[group]:
            grouped[group].append(label)
    return grouped


def _teacher_issue_group_for_item(item_id: str) -> str:
    normalized = item_id.lower()
    if normalized.startswith(("ht_", "history", "hf_")):
        return "history"
    if normalized.startswith(("pe_", "exam", "physical")):
        return "physical_exam"
    if normalized.startswith(("ax_", "at_", "lab", "image", "test")):
        return "auxiliary_test"
    if normalized.startswith(("rs_", "dxd_", "dx_", "diagnosis", "reasoning")):
        return "reasoning"
    if "exam" in normalized or "rebound" in normalized or "tender" in normalized:
        return "physical_exam"
    if "test" in normalized or "cbc" in normalized or "crp" in normalized or "urine" in normalized:
        return "auxiliary_test"
    return "reasoning"


def _coverage_map_labels_by_group(
    report: dict[str, Any],
    status: str,
    *,
    limit_per_group: int,
    case: Case | None = None,
) -> dict[str, list[str]]:
    snapshot = report.get("training_progress_snapshot")
    coverage_map = snapshot.get("coverage_map") if isinstance(snapshot, dict) else None
    if not isinstance(coverage_map, dict):
        return {}
    group_map = {
        "history": "history",
        "physical_exam": "physical_exam",
        "auxiliary_test": "auxiliary_test",
        "reasoning": "reasoning",
    }
    result: dict[str, list[str]] = {}
    for coverage_group, issue_group in group_map.items():
        items = coverage_map.get(coverage_group, [])
        if not isinstance(items, list):
            continue
        labels: list[str] = []
        for item in items:
            if not isinstance(item, dict) or item.get("status") != status:
                continue
            label = _teacher_training_point_label(item, case)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit_per_group:
                break
        if labels:
            result[issue_group] = labels
    return result


def _build_reasoning_chain_review(*, case_title: str, major_issues: list[dict[str, Any]]) -> str:
    issue_titles = [str(issue.get("title", "")) for issue in major_issues[:3] if issue.get("title")]
    if issue_titles:
        return (
            f"围绕「{case_title}」，更合理的训练路径是：先补全病史时间线，再用查体验证局部体征，"
            "随后选择必要检查支持或排除诊断，最后把阳性依据和阴性依据组织成诊断推理。"
            f"本轮需要优先修正的是{_compact_list_text(issue_titles, limit=3, fallback='证据链闭合')}。"
        )
    return (
        f"围绕「{case_title}」，你已经完成主要证据链。下一步要练习把证据按支持、反证和未确定问题三类表达出来。"
    )


def _build_next_practice_plan(major_issues: list[dict[str, Any]], pending_labels: list[str]) -> list[str]:
    plan = [str(issue.get("next_action", "")).strip() for issue in major_issues if str(issue.get("next_action", "")).strip()]
    plan = _dedupe_texts(plan)
    if pending_labels:
        plan.insert(0, f"先补齐{_compact_list_text(pending_labels, limit=3, fallback='未覆盖关键线索')}。")
    if not plan:
        plan = ["下一轮先整理支持依据、排除依据和仍需验证的问题，再提交诊断。"]
    return plan[:5]


def _dedupe_texts(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _coverage_map_labels(report: dict[str, Any], status: str, *, limit: int, case: Case | None = None) -> list[str]:
    snapshot = report.get("training_progress_snapshot")
    coverage_map = snapshot.get("coverage_map") if isinstance(snapshot, dict) else None
    if not isinstance(coverage_map, dict):
        return []

    labels: list[str] = []
    for group in ["history", "physical_exam", "auxiliary_test", "reasoning"]:
        items = coverage_map.get(group, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("status") != status:
                continue
            label = _teacher_training_point_label(item, case)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                return labels
    return labels


def _teacher_training_point_label(item: dict[str, Any], case: Case | None) -> str:
    item_id = str(item.get("id", "")).strip()
    if case and item_id:
        label = _case_training_point_label(case, item_id)
        if label:
            return label
    raw_label = str(item.get("label", "")).strip()
    return _strip_answer_value_from_label(raw_label)


def _case_training_point_label(case: Case, item_id: str) -> str:
    full_item_id = item_id if item_id.startswith(f"{case.case_id}.") else f"{case.case_id}.{item_id}"
    for fact in case.history.hidden_facts:
        if item_id in {fact.fact_id, fact.fact_id.removeprefix(f"{case.case_id}.")} or full_item_id == fact.fact_id:
            if fact.linked_rubric_items:
                linked_labels = rubric_item_labels(fact.linked_rubric_items[:1], [case.case_id])
                label = linked_labels[0] if linked_labels else ""
                if label:
                    return label
            if fact.slot:
                return HISTORY_SLOT_TRAINING_LABELS.get(str(fact.slot), f"追问{fact.topic}")
            return f"追问{fact.topic}"
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if item_id == exam.exam_code:
            if exam.linked_rubric_items:
                linked_labels = rubric_item_labels(exam.linked_rubric_items[:1], [case.case_id])
                label = linked_labels[0] if linked_labels else ""
                if label:
                    return label
            return exam.exam_name_cn
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if item_id == test.test_code:
            if test.linked_rubric_items:
                linked_labels = rubric_item_labels(test.linked_rubric_items[:1], [case.case_id])
                label = linked_labels[0] if linked_labels else ""
                if label:
                    return label
            return test.test_name_cn
    for reasoning_point in case.diagnosis.reasoning_points:
        if item_id in {reasoning_point.point_id, reasoning_point.point_id.removeprefix(f"{case.case_id}.")}:
            return reasoning_point.statement
    return ""


def _strip_answer_value_from_label(label: str) -> str:
    normalized = str(label).strip()
    if not normalized:
        return ""
    for delimiter in ("：", ":"):
        if delimiter not in normalized:
            continue
        prefix = normalized.split(delimiter, 1)[0].strip(" 。，；;")
        if 1 <= len(prefix) <= 32:
            return prefix
    return normalized


def _compact_list_text(items: list[str], *, limit: int, fallback: str) -> str:
    clean_items: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in clean_items:
            clean_items.append(normalized)
    if not clean_items:
        return fallback
    selected_items = clean_items[:limit]
    suffix = f"等 {len(clean_items)} 项" if len(clean_items) > limit else ""
    return "、".join(selected_items) + suffix


def _score_text(report: dict[str, Any]) -> str:
    total_score = report.get("total_score")
    max_score = report.get("max_score")
    if isinstance(total_score, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
        return f"{total_score:g}/{max_score:g} 分"
    if isinstance(total_score, (int, float)):
        return f"{total_score:g} 分"
    return "已生成评分"


def _append_personal_skill_events(
    *,
    candidate: dict[str, Any],
    review: dict[str, Any],
    event_store: TrainingEventStore,
    session: Any,
    skill_id: str,
) -> None:
    event_store.append_event(
        session_id=str(session.session_id),
        case_id=str(session.case_id),
        student_id=str(session.student_id),
        event_type="personal_training_skill_generated",
        payload={
            "candidate_id": candidate["candidate_id"],
            "skill_id": skill_id if review["status"] == "approved" else None,
            "review_status": review["status"],
            "scope": "personal",
            "web_check_status": candidate.get("web_check_status", "not_configured"),
        },
    )
    for event_type, payload in [
        (
            "personal_skill_candidate_generated",
            {
                "candidate_id": candidate["candidate_id"],
                "source_session_id": candidate["source_session_id"],
                "source_report_ids": list(candidate.get("source_report_ids", [])),
            },
        ),
        (
            "personal_skill_candidate_agent_reviewed",
            {
                "candidate_id": candidate["candidate_id"],
                "review_status": review["status"],
                "approval_dialogue": list(candidate.get("approval_dialogue", [])),
                "web_check_status": candidate.get("web_check_status", "not_configured"),
            },
        ),
    ]:
        event_store.append_event(
            session_id=str(candidate["candidate_id"]),
            case_id=str(candidate["trigger_item_id"]),
            student_id=AUTO_APPROVAL_AGENT_ID,
            event_type=event_type,
            payload=payload,
        )
    if review["status"] == "approved":
        event_store.append_event(
            session_id=str(candidate["candidate_id"]),
            case_id=str(candidate["trigger_item_id"]),
            student_id=AUTO_APPROVAL_AGENT_ID,
            event_type="personal_skill_candidate_auto_enabled",
            payload={
                "candidate_id": candidate["candidate_id"],
                "skill_id": skill_id,
                "scope": "personal",
                "owner_student_id": candidate["owner_student_id"],
            },
        )


def _report_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    review = candidate.get("review", {})
    skill_id = _personal_skill_id(str(candidate.get("source_session_id", "") or "").strip())
    if not skill_id:
        skill_id = f"skill_{candidate['trigger_item_id']}"
    return {
        "status": review.get("status", candidate.get("status", "draft")),
        "candidate_id": candidate["candidate_id"],
        "skill_id": skill_id,
        "title": candidate["title"],
        "description": candidate.get("description", ""),
        "suggested_strategy": candidate.get("suggested_strategy", ""),
        "scope": candidate.get("scope", "personal"),
        "owner_student_id": candidate.get("owner_student_id", ""),
        "source_session_id": candidate.get("source_session_id", ""),
        "source_report_ids": list(candidate.get("source_report_ids", [])),
        "trigger_item_ids": list(candidate.get("trigger_item_ids", [])),
        "review": review,
        "approval_agent_review": candidate.get("approval_agent_review", {}),
        "approval_dialogue": list(candidate.get("approval_dialogue", [])),
        "rag_evidence_items": list(candidate.get("rag_evidence_items", [])),
        "web_check_status": candidate.get("web_check_status", "not_configured"),
        "external_evidence_checks": list(candidate.get("external_evidence_checks", [])),
    }


def _personal_candidate_id(session_id: str) -> str:
    return f"personal_skill_candidate_{session_id}"


def _personal_skill_id(session_id: str) -> str:
    return f"skill_personal_{session_id}" if session_id else ""


personal_training_skill_service = PersonalTrainingSkillService()
