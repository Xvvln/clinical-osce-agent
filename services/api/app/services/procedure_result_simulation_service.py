from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.models.case import Case
from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.model_call_policy import ModelProviderPolicyError
from app.services.procedure_result_approval_agent import (
    ProcedureResultApprovalRequest,
    create_default_procedure_result_approval_agent,
)
from app.services.procedure_result_simulator import (
    ProcedureResultSimulationRequest,
    create_default_procedure_result_simulator,
)


PROCEDURE_SIMULATION_SAFETY_BOUNDARY = (
    "AI 模拟补充结果仅用于高级训练反馈，基于脱敏病例事实生成并经一致性审核；"
    "不写入病例标准事实，不进入标准评分。"
)
PROCEDURE_SIMULATION_POLICY_REFERENCE = (
    "policy:advanced_procedure_simulation.not_for_scoring"
)


@dataclass(frozen=True)
class ProcedureSimulationBatch:
    results: list[dict[str, Any]]
    new_audit_items: list[dict[str, Any]]


class ProcedureResultSimulationService:
    def __init__(
        self,
        *,
        procedure_result_simulator: Any | None = None,
        procedure_result_approval_agent: Any | None = None,
    ) -> None:
        self.procedure_result_simulator = (
            procedure_result_simulator or create_default_procedure_result_simulator()
        )
        self.procedure_result_approval_agent = (
            procedure_result_approval_agent
            or create_default_procedure_result_approval_agent()
        )

    def simulate(
        self,
        *,
        case: Case,
        request_text: str,
        matched_procedure_results: list[dict[str, Any]],
        existing_audit_items: list[dict[str, Any]],
        forbidden_terms: list[str],
    ) -> ProcedureSimulationBatch:
        patient_context = _procedure_simulation_patient_context(case)
        configured_results = _procedure_simulation_configured_results(case)
        results: list[dict[str, Any]] = []
        newly_generated_results: list[dict[str, Any]] = []

        for procedure_result in matched_procedure_results:
            if procedure_result.get("availability_status") != "not_available_for_case":
                results.append(procedure_result)
                continue

            cached_result = _cached_procedure_simulation_result(
                existing_audit_items,
                procedure_result,
            )
            if cached_result is not None:
                results.append(cached_result)
                continue

            if str(procedure_result.get("kind") or "") not in {
                "physical_exam",
                "auxiliary_test",
                "vital_sign",
            }:
                results.append(
                    _unavailable_result(
                        procedure_result,
                        approval_status="unsupported_simulation_kind",
                    )
                )
                continue

            knowledge_context = _retrieve_procedure_simulation_context(
                case=case,
                request_text=request_text,
                procedure_result=procedure_result,
                forbidden_terms=forbidden_terms,
            )
            try:
                simulation = self.procedure_result_simulator(
                    ProcedureResultSimulationRequest(
                        case_id=case.case_id,
                        case_title=case.case_title,
                        chief_complaint=case.chief_complaint,
                        request_text=request_text,
                        procedure_kind=str(procedure_result.get("kind", "")),
                        procedure_code=str(procedure_result.get("code", "")),
                        procedure_name_cn=str(procedure_result.get("name_cn", "")),
                        patient_context=patient_context,
                        configured_results=configured_results,
                        retrieved_knowledge_context=knowledge_context,
                        forbidden_terms=forbidden_terms,
                    )
                )
            except ModelProviderPolicyError:
                raise
            except Exception:
                results.append(
                    _unavailable_result(
                        procedure_result,
                        approval_status="simulation_unavailable",
                    )
                )
                continue

            simulation_text = _safe_simulated_procedure_result_text(
                getattr(simulation, "result", ""),
                forbidden_terms,
            )
            if not simulation_text:
                results.append(
                    _unavailable_result(
                        procedure_result,
                        approval_status="blocked_by_local_safety_gate",
                    )
                )
                continue

            simulation_confidence = str(
                getattr(simulation, "confidence", "conservative_inference")
                or "conservative_inference"
            )
            grounding_basis = _grounding_source_labels(
                patient_context=patient_context,
                configured_results=configured_results,
                knowledge_context=knowledge_context,
            )
            try:
                approval_review = _normalize_procedure_simulation_approval_review(
                    self.procedure_result_approval_agent(
                        ProcedureResultApprovalRequest(
                            case_id=case.case_id,
                            case_title=case.case_title,
                            chief_complaint=case.chief_complaint,
                            request_text=request_text,
                            procedure_kind=str(procedure_result.get("kind", "")),
                            procedure_code=str(procedure_result.get("code", "")),
                            procedure_name_cn=str(procedure_result.get("name_cn", "")),
                            simulated_result=simulation_text,
                            simulation_confidence=simulation_confidence,
                            grounding_basis=grounding_basis,
                            patient_context=patient_context,
                            configured_results=configured_results,
                            retrieved_knowledge_context=knowledge_context,
                            source_context_references=[
                                str(item.get("reference"))
                                for item in knowledge_context
                                if item.get("reference")
                            ],
                            forbidden_terms=forbidden_terms,
                        )
                    )
                )
            except ModelProviderPolicyError:
                raise
            except Exception:
                approval_review = _procedure_approval_fail_closed_review()

            approval_decision = str(approval_review.get("decision") or "blocked")
            if approval_decision == "revise":
                simulation_text = _safe_simulated_procedure_result_text(
                    approval_review.get("revised_result"),
                    forbidden_terms,
                )
                if not simulation_text:
                    approval_decision = "blocked"
                    approval_review = {
                        **approval_review,
                        "decision": "blocked",
                        "safety_issues": [
                            *list(approval_review.get("safety_issues") or []),
                            "审核改写结果为空或仍包含受保护内容。",
                        ],
                    }
            if approval_decision not in {"approved", "revise"}:
                results.append(
                    _unavailable_result(
                        procedure_result,
                        approval_status="blocked_by_consistency_gate",
                        approval_agent_review=approval_review,
                    )
                )
                continue

            unsupported_numeric_tokens = _unsupported_numeric_tokens(
                simulation_text,
                grounding_context={
                    "patient_context": patient_context,
                    "configured_results": configured_results,
                    "knowledge_context": knowledge_context,
                },
            )
            if (
                simulation_confidence == "conservative_inference"
                and unsupported_numeric_tokens
            ):
                results.append(
                    _unavailable_result(
                        procedure_result,
                        approval_status="blocked_by_unsupported_precision_gate",
                        approval_agent_review={
                            **approval_review,
                            "decision": "blocked",
                            "rationale": "保守推断包含病例依据中不存在的精确数值，已阻断展示。",
                            "safety_issues": [
                                *list(approval_review.get("safety_issues") or []),
                                "unsupported_numeric_precision",
                            ],
                        },
                    )
                )
                continue

            accepted_result = {
                **procedure_result,
                "result": f"AI 模拟：{simulation_text}（训练参考，不进入评分。）",
                "availability_status": "ai_simulated_for_training",
                "generated_by_ai": True,
                "approval_status": (
                    "revised_by_consistency_gate"
                    if approval_decision == "revise"
                    else "approved_by_consistency_gate"
                ),
                "approval_agent_review": approval_review,
                "generation_metadata": {
                    "confidence": simulation_confidence,
                    "grounding_basis": grounding_basis,
                },
                "source_context_references": [
                    "case_grounding:deidentified_case_facts",
                    *[
                        str(item.get("reference"))
                        for item in knowledge_context
                        if item.get("reference")
                    ],
                    PROCEDURE_SIMULATION_POLICY_REFERENCE,
                ],
                "scoring_eligible": False,
            }
            results.append(accepted_result)
            newly_generated_results.append(accepted_result)

        return ProcedureSimulationBatch(
            results=results,
            new_audit_items=_procedure_simulation_audit_items_from_results(
                newly_generated_results
            ),
        )


def merge_procedure_simulation_audit_items(
    existing_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for item in [*existing_items, *new_items]:
        procedure_id = str(item.get("procedure_id") or "")
        if not procedure_id:
            continue
        if procedure_id not in merged_by_id:
            ordered_ids.append(procedure_id)
        merged_by_id[procedure_id] = dict(item)
    return [merged_by_id[procedure_id] for procedure_id in ordered_ids]


def _unavailable_result(
    procedure_result: dict[str, Any],
    *,
    approval_status: str,
    approval_agent_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unavailable = {
        **procedure_result,
        "availability_status": "not_available_for_case",
        "generated_by_ai": False,
        "approval_status": approval_status,
        "source_context_references": [PROCEDURE_SIMULATION_POLICY_REFERENCE],
        "scoring_eligible": False,
    }
    if approval_agent_review is not None:
        unavailable["approval_agent_review"] = approval_agent_review
    return unavailable


def _cached_procedure_simulation_result(
    audit_items: list[dict[str, Any]],
    procedure_result: dict[str, Any],
) -> dict[str, Any] | None:
    procedure_id = str(procedure_result.get("id") or "")
    for audit_item in reversed(audit_items):
        if str(audit_item.get("procedure_id") or "") != procedure_id:
            continue
        if audit_item.get("scoring_eligible") is True:
            continue
        result_text = str(audit_item.get("result") or "").strip()
        if not result_text:
            continue
        approval_status = str(audit_item.get("approval_status") or "")
        approval_review = _normalize_procedure_simulation_approval_review(
            audit_item.get("approval_agent_review", {})
        )
        if not approval_status.startswith(("approved_", "revised_")):
            continue
        if approval_review["decision"] not in {"approved", "revise"}:
            continue
        return {
            **procedure_result,
            "result": result_text,
            "availability_status": "ai_simulated_for_training",
            "generated_by_ai": True,
            "approval_status": approval_status,
            "approval_agent_review": approval_review,
            "generation_metadata": dict(
                audit_item.get("generation_metadata")
                if isinstance(audit_item.get("generation_metadata"), dict)
                else {}
            ),
            "source_context_references": [
                str(reference)
                for reference in audit_item.get("source_context_references", [])
                if str(reference).strip()
            ],
            "scoring_eligible": False,
        }
    return None


def _procedure_simulation_audit_items_from_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "procedure_id": str(result.get("id") or ""),
            "kind": _procedure_audit_kind(str(result.get("kind") or "")),
            "code": str(result.get("code") or ""),
            "label": str(
                result.get("name_cn")
                or result.get("label")
                or result.get("code")
                or ""
            ),
            "result": str(result.get("result") or ""),
            "approval_status": str(result.get("approval_status") or ""),
            "approval_agent_review": _normalize_procedure_simulation_approval_review(
                result.get("approval_agent_review", {})
            ),
            "generation_metadata": dict(
                result.get("generation_metadata")
                if isinstance(result.get("generation_metadata"), dict)
                else {}
            ),
            "source_context_references": [
                str(reference)
                for reference in result.get("source_context_references", [])
                if str(reference).strip()
            ],
            "scoring_eligible": False,
            "safety_boundary": PROCEDURE_SIMULATION_SAFETY_BOUNDARY,
        }
        for result in results
        if result.get("generated_by_ai") is True
    ]


def _normalize_procedure_simulation_approval_review(review: Any) -> dict[str, Any]:
    if hasattr(review, "model_dump"):
        review = review.model_dump()
    if not isinstance(review, dict):
        review = {}
    decision = str(review.get("decision") or "blocked")
    if decision not in {"approved", "revise", "blocked"}:
        decision = "blocked"
    return {
        "agent_id": str(
            review.get("agent_id") or "procedure_result_approval_agent"
        ),
        "decision": decision,
        "approval_mode": str(
            review.get("approval_mode") or "consistency_gate_fail_closed"
        ),
        "rationale": str(review.get("rationale") or ""),
        "safety_issues": [
            str(item)
            for item in review.get("safety_issues", [])
            if str(item).strip()
        ],
        "revised_result": str(review.get("revised_result") or ""),
    }


def _procedure_approval_fail_closed_review() -> dict[str, Any]:
    return {
        "agent_id": "procedure_result_approval_agent",
        "decision": "blocked",
        "approval_mode": "consistency_gate_error_fail_closed",
        "rationale": "一致性审核不可用，已阻断模拟结果展示。",
        "safety_issues": ["approval_agent_unavailable"],
        "revised_result": "",
    }


def _safe_simulated_procedure_result_text(
    result: Any,
    forbidden_terms: list[str],
) -> str:
    normalized = re.sub(r"\s+", " ", str(result or "")).strip()
    if not normalized:
        return ""
    protected_terms = [
        *forbidden_terms,
        "治疗方案",
        "用药剂量",
        "手术方案",
        "处置建议",
        "标准答案",
        "rubric",
    ]
    if any(
        term and re.search(re.escape(term), normalized, flags=re.IGNORECASE)
        for term in protected_terms
    ):
        return ""
    if len(normalized) > 160:
        normalized = f"{normalized[:157]}..."
    return normalized


def _grounding_source_labels(
    *,
    patient_context: dict[str, Any],
    configured_results: list[dict[str, str]],
    knowledge_context: list[dict[str, Any]],
) -> list[str]:
    labels: list[str] = []
    if patient_context:
        labels.append("脱敏病例临床表现")
    if configured_results:
        labels.append("病例已配置查体与检查所见")
    if knowledge_context:
        labels.append("提交前安全教学知识片段")
    return labels


def _unsupported_numeric_tokens(
    result_text: str,
    *,
    grounding_context: dict[str, Any],
) -> list[str]:
    grounding_text = json.dumps(grounding_context, ensure_ascii=False)
    numeric_tokens = re.findall(
        r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])",
        result_text,
    )
    return [
        token
        for token in dict.fromkeys(numeric_tokens)
        if token not in grounding_text
    ]


def _procedure_audit_kind(kind: str) -> str:
    if kind == "auxiliary_test":
        return "test"
    if kind == "physical_exam":
        return "exam"
    return kind


def _retrieve_procedure_simulation_context(
    *,
    case: Case,
    request_text: str,
    procedure_result: dict[str, Any],
    forbidden_terms: list[str],
) -> list[dict[str, Any]]:
    try:
        # Reuse only the already-approved pre-submit Coach corpus.  The
        # simulator never gains post-submit or secret-scoring visibility.
        return retrieve_agent_context(
            agent_role="coach",
            case_ids=[case.case_id],
            query_terms=[
                case.chief_complaint,
                request_text,
                str(procedure_result.get("name_cn", "")),
                str(procedure_result.get("code", "")),
            ],
            allowed_visibilities={"pre_submit_safe"},
            forbidden_terms=forbidden_terms,
            limit=3,
        )
    except Exception:
        return []


def _procedure_simulation_patient_context(case: Case) -> dict[str, Any]:
    return {
        "age": f"{case.patient_profile.age_value}{case.patient_profile.age_unit}",
        "gender": case.patient_profile.gender,
        "occupation": case.patient_profile.occupation,
        "department": case.patient_profile.hospital_department,
        "chief_complaint": case.chief_complaint,
        "present_illness_summary": case.history.present_illness_summary,
        "history_facts": [
            {
                "topic": fact.topic,
                "slot": fact.slot,
                "answer": fact.canonical_answer,
            }
            for fact in case.history.hidden_facts
        ],
    }


def _procedure_simulation_configured_results(
    case: Case,
) -> list[dict[str, str]]:
    return [
        *[
            {
                "kind": "physical_exam",
                "code": item.exam_code,
                "name_cn": item.exam_name_cn,
                "result": item.result,
            }
            for item in [
                *case.physical_exam.must_items,
                *case.physical_exam.optional_items,
            ]
        ],
        *[
            {
                "kind": "auxiliary_test",
                "code": item.test_code,
                "name_cn": item.test_name_cn,
                "result": item.result,
            }
            for item in [
                *case.auxiliary_tests.must_items,
                *case.auxiliary_tests.optional_items,
            ]
        ],
    ]


__all__ = [
    "PROCEDURE_SIMULATION_SAFETY_BOUNDARY",
    "ProcedureResultSimulationService",
    "ProcedureSimulationBatch",
    "merge_procedure_simulation_audit_items",
]
