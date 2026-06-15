from __future__ import annotations

import re
from typing import Any

MEMORY_LAYER = "procedural_teaching_skill"
SKILL_MEMORY_VERSION = "skill_memory_v1"
REFLECTION_PROMPT_TEMPLATE = "训练结束后，请对照本轮反复漏掉的评分项复盘证据链，不补写标准答案或隐藏事实。"
SKILL_ROUTER_WHEN_NOT_TO_USE = "空白开局、学生尚未暴露相关错误模式、该问题已冷却/退休，或提示会泄露标准答案 / 隐藏事实时不要使用。"
SKILL_ROUTER_RISK = "仅用于教学提示和复盘，不得透露标准诊断、隐藏事实或真实临床处理细节。"

SKILL_TYPE_GAP_LABELS = {
    "history_bundle": "病史采集结构化不足",
    "exam_bundle": "查体策略与体征验证不足",
    "test_strategy": "辅助检查选择与解释不足",
    "reasoning_bridge": "证据链整合与推理表达不足",
    "differential_broadening": "鉴别诊断与证据链拓展不足",
    "workflow_sequencing": "训练流程顺序与验证链衔接不足",
    "conversation_repair": "问诊目标聚焦与沟通修复不足",
    "safety_boundary": "教学边界与安全意识不足",
    "narrative_perspective": "患者叙事、担忧期待与生活影响理解不足",
    "communication_structure": "沟通结构、总结确认与理解校验不足",
    "ethics_consent": "知情同意、隐私舒适度与患者自主尊重不足",
    "relationship_repair": "情绪回应、支持性语言与合作关系建立不足",
}

FOCUS_ITEM_PREFIX_LABELS = {
    "ht": "病史采集",
    "history": "病史采集",
    "pe": "查体",
    "exam": "查体",
    "lab": "实验室检查",
    "img": "影像检查",
    "aux": "辅助检查",
    "test": "辅助检查",
    "at": "辅助检查",
    "dxd": "鉴别诊断",
    "rs": "推理表达",
    "reasoning": "推理表达",
    "diagnosis": "诊断判断",
    "workflow": "训练流程",
    "sequence": "训练顺序",
    "turn": "对话轮次",
    "event": "训练事件",
    "nm": "叙事医学",
    "comm": "沟通技巧",
    "eth": "医学伦理",
    "rel": "关系建立",
}

FOCUS_ITEM_TOKEN_LABELS = {
    "abd": "腹部",
    "abdominal": "腹部",
    "allergy": "过敏史",
    "auxiliary": "辅助检查",
    "character": "疼痛性质",
    "crohn": "克罗恩病",
    "differential": "鉴别诊断",
    "duration": "持续时间",
    "ectopic": "异位妊娠",
    "evidence": "证据",
    "exam": "查体",
    "exclude": "排除依据",
    "fever": "发热",
    "history": "病史",
    "ice": "患者想法、担忧与期望",
    "location": "疼痛部位及转移特征",
    "migration": "疼痛迁移",
    "nausea": "恶心",
    "onset": "起病时间",
    "pain": "疼痛",
    "past": "既往史",
    "reasoning": "推理",
    "severity": "疼痛程度",
    "support": "支持证据",
    "tenderness": "压痛",
    "urolith": "输尿管结石",
    "vomit": "呕吐",
    "core": "核心证据链",
    "autonomy": "尊重自主",
    "collaborative": "合作式表达",
    "comfort": "舒适度",
    "concern": "担忧",
    "confirm": "确认理解",
    "consent": "知情同意",
    "empathy": "共情回应",
    "intro": "自我介绍",
    "life": "生活影响",
    "medicine": "医学",
    "narrative": "叙事",
    "open": "开放式提问",
    "patient": "患者视角",
    "perspective": "患者视角",
    "privacy": "隐私保护",
    "purpose": "目的说明",
    "relationship": "医患关系",
    "response": "回应",
    "summary": "阶段性总结",
    "supportive": "支持性语言",
}

STAGE_LABELS = {
    "case_intro": "训练开始",
    "history_taking": "问诊",
    "physical_exam": "查体",
    "auxiliary_testing": "辅助检查",
    "auxiliary_test": "辅助检查",
    "diagnosis_submission": "诊断提交",
    "diagnosis": "诊断整理",
    "feedback": "训练反馈",
    "feedback_review": "训练反馈",
}

EFFECT_STATUS_LABELS = {
    "insufficient_samples": "样本不足",
    "improving": "观察到改善",
    "neutral": "效果待观察",
    "declining": "需要复核",
}


def build_teaching_action_plan(
    *,
    stage_scope: list[str],
    trigger_item_ids: list[str],
    suggested_strategy: str,
) -> list[dict[str, Any]]:
    diagnosis_stage_scope = [stage for stage in stage_scope if stage == "diagnosis_submission"]
    if not diagnosis_stage_scope:
        diagnosis_stage_scope = ["diagnosis_submission"]
    return [
        {
            "action_type": "hint_ladder",
            "level": 1,
            "stage_scope": list(stage_scope),
            "trigger_item_ids": list(trigger_item_ids),
            "message_template": suggested_strategy,
        },
        {
            "action_type": "reflection_prompt",
            "level": 1,
            "stage_scope": diagnosis_stage_scope,
            "trigger_item_ids": list(trigger_item_ids),
            "message_template": REFLECTION_PROMPT_TEMPLATE,
        },
    ]


def build_prohibited_content_policy() -> dict[str, Any]:
    return {
        "forbid_main_diagnosis": True,
        "forbid_hidden_facts": True,
        "forbid_test_results": True,
        "forbid_treatment_plan": True,
        "forbid_dose": True,
        "allowed_scope": "teaching_strategy_only",
    }


def build_success_metrics() -> list[str]:
    return [
        "target_rubric_item_recovery_rate",
        "stage_completion_rate",
        "hint_after_skill_usage",
    ]


def build_skill_memory_fields(
    *,
    pattern_id: str,
    skill_type: str,
    trigger_item_ids: list[str],
    case_ids: list[str],
    source_report_count: int,
    support_count: int,
    title: str,
    description: str,
    suggested_strategy: str,
    stage_scope: list[str],
    effect_status: str = "insufficient_samples",
    reasoning_pattern_ids: list[str] | None = None,
    reasoning_pattern_labels: list[str] | None = None,
    trigger_item_labels: list[str] | None = None,
    application_count: int = 0,
) -> dict[str, Any]:
    reasoning_pattern_ids = list(reasoning_pattern_ids or [])
    reasoning_pattern_labels = list(reasoning_pattern_labels or [])
    focus_points = _focus_points(
        trigger_item_ids=trigger_item_ids,
        trigger_item_labels=trigger_item_labels,
        reasoning_pattern_labels=reasoning_pattern_labels,
    )
    return {
        "memory_layer": MEMORY_LAYER,
        "skill_memory_version": SKILL_MEMORY_VERSION,
        "problem_pattern": {
            "pattern_id": pattern_id,
            "pattern_type": skill_type,
            "clinical_reasoning_gap": _clinical_reasoning_gap(skill_type),
            "trigger_item_ids": list(trigger_item_ids),
            "reasoning_pattern_ids": reasoning_pattern_ids,
            "reasoning_pattern_labels": reasoning_pattern_labels,
            "case_ids": list(case_ids),
            "source_report_count": int(source_report_count),
            "support_count": int(support_count),
        },
        "router_index": {
            "summary": _router_summary(title, description),
            "when_to_use": _router_when_to_use(skill_type, stage_scope),
            "when_not_to_use": SKILL_ROUTER_WHEN_NOT_TO_USE,
            "risk": SKILL_ROUTER_RISK,
        },
        "intervention": {
            "teaching_goal": _clinical_reasoning_gap(skill_type),
            "coach_strategy": suggested_strategy,
            "focus_points": focus_points,
            "hint_ladder": _hint_ladder(skill_type, focus_points),
            "teaching_sop": _teaching_sop(skill_type, focus_points, stage_scope),
            "reflection_prompt": REFLECTION_PROMPT_TEMPLATE,
            "avoid": [
                "不得透露标准诊断。",
                "不得补写隐藏事实或未申请的检查结果。",
                "不得给出真实临床处理细节。",
            ],
        },
        "effect_tracking": {
            "status": effect_status,
            "status_label": EFFECT_STATUS_LABELS.get(effect_status, effect_status),
            "support_count": int(support_count),
            "source_report_count": int(source_report_count),
            "application_count": int(application_count),
            "summary": _effect_tracking_summary(effect_status),
        },
    }


def _clinical_reasoning_gap(skill_type: str) -> str:
    return SKILL_TYPE_GAP_LABELS.get(skill_type, "临床思维训练模式需要巩固")


def _focus_points(
    *,
    trigger_item_ids: list[str],
    trigger_item_labels: list[str] | None,
    reasoning_pattern_labels: list[str],
) -> list[str]:
    labels: list[str] = []
    resolved_labels = list(trigger_item_labels or [])
    for index, item_id in enumerate(trigger_item_ids):
        label = resolved_labels[index] if index < len(resolved_labels) else ""
        _append_unique(labels, _readable_focus_label(item_id, label))
    for label in reasoning_pattern_labels:
        _append_unique(labels, str(label or "").strip())
    return labels[:4]


def _append_unique(labels: list[str], label: str) -> None:
    normalized_label = str(label or "").strip()
    if normalized_label and normalized_label not in labels:
        labels.append(normalized_label)


def _readable_focus_label(item_id: str, label: str) -> str:
    normalized_item_id = str(item_id or "").strip()
    normalized_label = str(label or "").strip()
    if (
        normalized_label
        and normalized_label != normalized_item_id
        and not normalized_label.startswith("未收录评分项：")
    ):
        return normalized_label
    return _humanize_item_id(normalized_item_id) or normalized_label or normalized_item_id


def _humanize_item_id(item_id: str) -> str:
    tokens = [token for token in re.split(r"[_:.\-]+", str(item_id or "")) if token]
    if not tokens:
        return ""
    prefix_label = FOCUS_ITEM_PREFIX_LABELS.get(tokens[0])
    translated_tokens = [FOCUS_ITEM_TOKEN_LABELS.get(token, "") for token in tokens[1:]]
    translated_tokens = [token for token in translated_tokens if token]
    if prefix_label and translated_tokens:
        return f"{prefix_label}：{'、'.join(translated_tokens)}"
    if translated_tokens:
        return "、".join(translated_tokens)
    return prefix_label or item_id


def _hint_ladder(skill_type: str, focus_points: list[str]) -> list[str]:
    focus = _focus_text(focus_points)
    if skill_type == "history_bundle":
        return [
            f"先让学生回顾已问到的病史线索，指出{focus}仍缺哪些关键信息。",
            f"再用反问方式引导学生补齐{focus}，要求说明这些信息如何形成问题表征。",
            "最后让学生决定补齐病史后下一步应选择哪类查体或检查，并说明目的。",
        ]
    if skill_type == "exam_bundle":
        return [
            f"先让学生说明当前病史支持哪些查体方向，重点围绕{focus}。",
            "再引导学生从一般状态到局部体征逐步选择查体项目，而不是一次性索要结论。",
            "最后让学生解释查体结果将如何支持或削弱现有诊断假设。",
        ]
    if skill_type == "test_strategy":
        return [
            f"先让学生列出目前还缺哪类客观证据，重点围绕{focus}。",
            "再引导学生区分支持诊断、排除危险疾病和鉴别诊断所需的检查。",
            "最后让学生说明每项检查结果如何改变下一步推理，而不是只堆叠检查名称。",
        ]
    if skill_type == "differential_broadening":
        return [
            f"先让学生列出当前主诊断假设之外还需要排除的方向，重点围绕{focus}。",
            "再引导学生为每个鉴别方向补齐支持证据、反对证据和必要检查，而不是只写一个诊断名。",
            "最后让学生说明新增证据如何改变诊断排序，并明确哪些依据仍然不足。",
        ]
    if skill_type == "reasoning_bridge":
        return [
            f"先让学生复盘已获得的症状、体征和检查线索，标出{focus}仍缺哪一环。",
            "再引导学生把每条证据写成“支持什么、排除什么、还缺什么”的链条，而不是只罗列事实。",
            "最后让学生用新增证据重新组织诊断假设和鉴别诊断，但不直接给出标准答案。",
        ]
    if skill_type == "workflow_sequencing":
        return [
            f"先让学生回看本轮操作顺序，标出{focus}在哪一步被过早跳过或延后。",
            "再引导学生说明为什么应先完成前置病史、查体或检查，再进入下一阶段。",
            "最后让学生给出下一轮更合理的训练顺序，并说明每一步的验证目的。",
        ]
    if skill_type == "conversation_repair":
        return [
            f"先让学生确认当前提问是否围绕{focus}，避免把患者带离病例情境。",
            "再引导学生把宽泛问题改写成可被患者回答的具体问句。",
            "最后让学生说明这个问题会补齐哪一类临床信息。",
        ]
    if skill_type == "safety_boundary":
        return [
            f"先让学生识别当前表达中与{focus}相关的安全边界。",
            "再引导学生把真实诊疗请求改写为教学模拟内的可练习目标。",
            "最后提醒学生只讨论训练策略和证据链，不输出真实诊疗建议。",
        ]
    return [
        f"先让学生回顾已获得信息与当前缺口，重点围绕{focus}。",
        "再引导学生补齐病史、查体、检查或推理链中最相关的一环。",
        "最后要求学生说明新增证据如何支持或排除诊断假设。",
    ]


def _teaching_sop(skill_type: str, focus_points: list[str], stage_scope: list[str]) -> dict[str, Any]:
    return {
        "version": "teaching_sop_v1",
        "clinical_reasoning_focus": _clinical_reasoning_focus(skill_type),
        "applicable_context": _router_when_to_use(skill_type, stage_scope),
        "teacher_moves": _teacher_moves(skill_type, focus_points),
        "student_task": _student_task(skill_type),
        "completion_signal": _completion_signal(skill_type),
        "safety_guardrails": [
            "不得透露标准诊断。",
            "不得补写病例隐藏事实或未申请检查结果。",
            "不得给出真实临床处理细节。",
        ],
    }


def _clinical_reasoning_focus(skill_type: str) -> list[str]:
    if skill_type == "history_bundle":
        return ["问题表征", "病史时间线", "伴随症状"]
    if skill_type == "exam_bundle":
        return ["体征验证", "局部查体选择", "假设检验"]
    if skill_type == "test_strategy":
        return ["检查选择", "客观证据", "排除危险疾病"]
    if skill_type == "differential_broadening":
        return ["鉴别诊断", "假设检验", "证据链完整性"]
    if skill_type == "reasoning_bridge":
        return ["证据链完整性", "诊断假设排序", "支持与排除依据"]
    if skill_type == "workflow_sequencing":
        return ["训练顺序", "前置证据", "阶段衔接"]
    if skill_type == "conversation_repair":
        return ["问诊聚焦", "问题改写", "患者可回答性"]
    if skill_type == "safety_boundary":
        return ["安全边界", "教学模拟边界", "风险表达"]
    return ["临床思维", "证据链", "下一步计划"]


def _teacher_moves(skill_type: str, focus_points: list[str]) -> list[dict[str, Any]]:
    focus = _focus_text(focus_points)
    if skill_type == "differential_broadening":
        moves = [
            (
                f"让学生先说出除当前主假设外还需要排除的方向，聚焦{focus}。",
                "拓宽鉴别诊断范围，避免只围绕单一诊断收集证据。",
                "socratic_question",
            ),
            (
                "追问每个鉴别方向分别需要哪些支持证据、反对证据和必要检查。",
                "把鉴别诊断从名称列表转化为可验证的证据链。",
                "evidence_mapping",
            ),
            (
                "要求学生说明新增证据会如何改变诊断排序，以及仍有哪些依据不足。",
                "训练动态修正假设，而不是直接确认答案。",
                "reasoning_recap",
            ),
        ]
    elif skill_type == "history_bundle":
        moves = [
            (
                f"让学生回顾已问到的病史，并点出{focus}仍缺哪些信息。",
                "建立完整问题表征，避免遗漏关键病史维度。",
                "socratic_question",
            ),
            (
                "引导学生把宽泛问题改成可由患者回答的具体问句。",
                "提升问诊问题的可回答性和信息密度。",
                "question_refinement",
            ),
            (
                "让学生解释补齐这些病史后会如何影响下一步查体或检查。",
                "把病史采集和后续验证动作连接起来。",
                "reasoning_recap",
            ),
        ]
    elif skill_type == "exam_bundle":
        moves = [
            (
                f"让学生先说明当前病史支持哪些查体方向，聚焦{focus}。",
                "让查体选择服务于假设验证，而不是机械罗列。",
                "socratic_question",
            ),
            (
                "引导学生从一般状态到局部体征逐步选择查体项目。",
                "训练从整体风险到局部证据的查体顺序。",
                "stepwise_planning",
            ),
            (
                "要求学生说明查体结果会支持或削弱哪一类诊断假设。",
                "把体征结果纳入证据链，而不是只读取结果。",
                "evidence_mapping",
            ),
        ]
    elif skill_type == "test_strategy":
        moves = [
            (
                f"让学生列出还缺哪类客观证据，聚焦{focus}。",
                "明确检查申请的诊断目的。",
                "socratic_question",
            ),
            (
                "引导学生区分支持诊断、鉴别诊断和排除危险疾病所需的检查。",
                "避免用检查堆叠替代临床推理。",
                "evidence_mapping",
            ),
            (
                "要求学生预判不同检查结果会如何改变下一步推理。",
                "训练检查结果解释和诊断假设更新。",
                "reasoning_recap",
            ),
        ]
    elif skill_type == "reasoning_bridge":
        moves = [
            (
                f"让学生把已获得线索按支持、反对、仍缺三类整理，聚焦{focus}。",
                "把零散事实组织成诊断证据链。",
                "evidence_mapping",
            ),
            (
                "追问学生每条证据具体支持什么、排除什么、还不能说明什么。",
                "减少只罗列事实、不解释意义的问题。",
                "socratic_question",
            ),
            (
                "要求学生重新组织诊断假设和鉴别诊断排序。",
                "训练基于证据的假设修正。",
                "reasoning_recap",
            ),
        ]
    elif skill_type == "workflow_sequencing":
        moves = [
            (
                f"让学生回看本轮操作顺序，指出{focus}在哪一步被跳过或提前。",
                "识别临床推理链中的顺序断点。",
                "socratic_question",
            ),
            (
                "引导学生说明为什么应先完成前置病史、查体或检查再进入下一阶段。",
                "强化阶段间因果关系。",
                "stepwise_planning",
            ),
            (
                "要求学生给出下一轮更合理的训练顺序。",
                "形成可复用的流程策略。",
                "reasoning_recap",
            ),
        ]
    elif skill_type == "conversation_repair":
        moves = [
            (
                f"让学生判断当前提问是否围绕{focus}。",
                "把偏离病例的问题拉回教学目标。",
                "socratic_question",
            ),
            (
                "引导学生把含糊或无关表达改写成患者可回答的问题。",
                "提升医患对话质量。",
                "question_refinement",
            ),
            (
                "要求学生说明这个问题会补齐哪类临床信息。",
                "建立问题与证据缺口之间的联系。",
                "reasoning_recap",
            ),
        ]
    elif skill_type == "safety_boundary":
        moves = [
            (
                f"让学生识别当前表达中与{focus}相关的安全边界。",
                "避免把教学模拟误用为真实诊疗。",
                "socratic_question",
            ),
            (
                "引导学生把真实诊疗请求改写为教学模拟内的训练目标。",
                "保持系统输出在训练策略范围内。",
                "question_refinement",
            ),
            (
                "要求学生只讨论证据链、训练动作和复盘策略。",
                "防止输出真实诊疗建议。",
                "safety_recap",
            ),
        ]
    else:
        moves = [
            (
                f"让学生回顾当前信息与缺口，聚焦{focus}。",
                "明确下一步教学目标。",
                "socratic_question",
            ),
            (
                "引导学生补齐最相关的一环病史、查体、检查或推理链。",
                "把提示转化为可执行训练动作。",
                "stepwise_planning",
            ),
            (
                "要求学生说明新增证据如何支持或排除诊断假设。",
                "强化证据链复盘。",
                "reasoning_recap",
            ),
        ]
    return [
        {
            "order": index,
            "move": move,
            "purpose": purpose,
            "prompt_style": prompt_style,
            "disclosure_boundary": "只提示下一步思考和训练动作，不给标准答案或隐藏事实。",
        }
        for index, (move, purpose, prompt_style) in enumerate(moves, start=1)
    ]


def _student_task(skill_type: str) -> str:
    if skill_type == "history_bundle":
        return "补齐关键病史维度，并说明这些信息如何形成问题表征。"
    if skill_type == "exam_bundle":
        return "选择与当前假设相关的查体项目，并说明每项查体要验证什么。"
    if skill_type == "test_strategy":
        return "选择必要辅助检查，并说明其支持、排除或鉴别诊断价值。"
    if skill_type == "differential_broadening":
        return "补齐每个鉴别方向的支持证据、反对证据和必要检查。"
    if skill_type == "reasoning_bridge":
        return "把症状、体征、检查和鉴别诊断组织成支持与排除证据链。"
    if skill_type == "workflow_sequencing":
        return "重排下一轮训练顺序，并解释每一步的前置条件。"
    if skill_type == "conversation_repair":
        return "把宽泛或偏离的问题改写为患者可回答、能补齐证据缺口的问句。"
    if skill_type == "safety_boundary":
        return "把真实诊疗请求转换为教学模拟内的训练问题。"
    return "补齐当前训练缺口，并说明新增证据如何影响下一步推理。"


def _completion_signal(skill_type: str) -> str:
    if skill_type == "history_bundle":
        return "学生能说清补齐后的病史如何改变问题表征和下一步验证计划。"
    if skill_type == "exam_bundle":
        return "学生能说明所选查体如何支持或削弱当前诊断假设。"
    if skill_type == "test_strategy":
        return "学生能说明每项检查的目的及其对诊断排序的影响。"
    if skill_type == "differential_broadening":
        return "学生能说明新增证据如何改变诊断排序，并指出仍缺的依据。"
    if skill_type == "reasoning_bridge":
        return "学生能用支持、排除和不确定证据重新组织诊断假设。"
    if skill_type == "workflow_sequencing":
        return "学生能给出更合理的下一轮训练顺序并解释原因。"
    if skill_type == "conversation_repair":
        return "学生能把提示转化为具体、聚焦、患者可回答的问题。"
    if skill_type == "safety_boundary":
        return "学生能保持教学模拟边界，不索要真实诊疗方案。"
    return "学生能说明新增证据如何支持或排除诊断假设。"


def _focus_text(focus_points: list[str]) -> str:
    labels = [label for label in focus_points if label]
    if not labels:
        return "当前训练缺口"
    return "、".join(labels[:3])


def _router_summary(title: str, description: str) -> str:
    title = str(title or "").strip()
    description = str(description or "").strip()
    if title and description:
        return f"{title}：{description}"
    return title or description


def _router_when_to_use(skill_type: str, stage_scope: list[str]) -> str:
    stage_summary = _stage_scope_summary(stage_scope)
    return f"当学生在{stage_summary}暴露出{_clinical_reasoning_gap(skill_type)}，且当前上下文命中关联训练点时使用。"


def _stage_scope_summary(stage_scope: list[str]) -> str:
    labels = [STAGE_LABELS.get(str(stage), str(stage)) for stage in stage_scope if str(stage)]
    if not labels:
        return "当前训练阶段"
    if labels == ["训练开始"]:
        return "训练开始阶段"
    return "、".join(dict.fromkeys(labels))


def _effect_tracking_summary(effect_status: str) -> str:
    if effect_status == "insufficient_samples":
        return "样本不足，仅记录应用痕迹，不宣称能力提升。"
    return f"{EFFECT_STATUS_LABELS.get(effect_status, effect_status)}，需要结合后续样本持续观察。"
