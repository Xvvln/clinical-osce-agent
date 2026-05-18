export type LlmReasoningFeedbackItem = Readonly<{
  rubric_item_id: string;
  description: string;
  score: number;
  max_score: number;
  covered_evidence: readonly string[];
  missing_evidence: readonly string[];
  rationale: string;
}>;

export type KnowledgeRecommendationItem = Readonly<{
  reference: string;
  title: string;
  reason: string;
}>;

export type SourceReferenceItem = Readonly<{
  reference: string;
  source_type: string;
  title: string;
  metadata: Readonly<Record<string, unknown>>;
}>;

export type ExplanationSourceItem = Readonly<{
  kind: string;
  text: string;
  rubric_item_id: string;
  source_references: readonly string[];
}>;

export type AiReflectionReview = Readonly<{
  status: string;
  reason?: string;
  summary: string;
  mistake_patterns: readonly string[];
  teacher_feedback: string;
  next_focus: string;
  source_references: readonly string[];
  source_reference_items: readonly SourceReferenceItem[];
  generated_by?: string;
  safety_note?: string;
}>;

export type PersonalTrainingSkillApprovalDialogueTurn = Readonly<{
  round: number;
  agent_id: string;
  decision: string;
  revision_status: string;
  changed_fields: readonly unknown[];
  rag_reference_count: number;
  web_check_status: string;
  blocking_failures: readonly unknown[];
  candidate_safety_violations: readonly string[];
  candidate_context_violations: readonly string[];
}>;

export type PersonalTrainingSkillCandidate = Readonly<{
  status: string;
  reason?: string;
  candidate_id: string | null;
  skill_id: string | null;
  title?: string;
  description?: string;
  suggested_strategy?: string;
  scope: string;
  owner_student_id?: string;
  source_session_id?: string;
  source_report_ids?: readonly string[];
  trigger_item_ids?: readonly string[];
  review?: Readonly<Record<string, unknown>>;
  approval_agent_review?: Readonly<Record<string, unknown>>;
  approval_dialogue?: readonly PersonalTrainingSkillApprovalDialogueTurn[];
  rag_evidence_items: readonly SourceReferenceItem[];
  web_check_status: string;
  external_evidence_checks: readonly unknown[];
}>;

export const DEFAULT_AI_REFLECTION_REVIEW: AiReflectionReview = {
  status: "legacy_report",
  reason: "ai_reflection_not_recorded",
  summary: "该历史报告生成时尚未记录 AI 复盘回顾。",
  mistake_patterns: [],
  teacher_feedback: "",
  next_focus: "",
  source_references: [],
  source_reference_items: [],
};

export const DEFAULT_PERSONAL_TRAINING_SKILL_CANDIDATE: PersonalTrainingSkillCandidate = {
  status: "legacy_report",
  reason: "personal_skill_not_recorded",
  candidate_id: null,
  skill_id: null,
  scope: "personal",
  rag_evidence_items: [],
  web_check_status: "not_configured",
  external_evidence_checks: [],
};

export type EvidenceGraphNodeItem = Readonly<{
  node_id: string;
  node_type: string;
  source_id: string;
  label: string;
}>;

export type EvidenceGraphEdgeItem = Readonly<{
  from_node: string;
  to_node: string;
  relation: string;
  from_label: string;
  to_label: string;
}>;

export type EvidenceGraphSummary = Readonly<{
  case_id: string;
  total_evidence_node_count: number;
  covered_evidence_node_count: number;
  missing_evidence_node_count: number;
  coverage_ratio: number;
  covered_evidence_nodes: readonly EvidenceGraphNodeItem[];
  missing_evidence_nodes: readonly EvidenceGraphNodeItem[];
  covered_edges: readonly EvidenceGraphEdgeItem[];
  missing_edges: readonly EvidenceGraphEdgeItem[];
  scoring_boundary: string;
}>;

export type ReportCoverageMapItem = Readonly<{
  id: string;
  label: string;
  status: "covered" | "pending";
}>;

export type ReportCoverageMapPayload = Readonly<{
  history: readonly ReportCoverageMapItem[];
  physical_exam: readonly ReportCoverageMapItem[];
  auxiliary_test: readonly ReportCoverageMapItem[];
  reasoning: readonly ReportCoverageMapItem[];
}>;

export type ReportTrainingProgressSnapshot = Readonly<{
  coverage_map: ReportCoverageMapPayload;
  next_focus?: string;
}>;

export type RubricScoreItem = Readonly<{
  score: number;
  max_score: number;
  dimension_id: string;
  description: string;
}>;

export type FeedbackReportPayload = Readonly<{
  session_id: string;
  case_id: string;
  total_score: number;
  dimension_scores: Readonly<Record<string, number>>;
  rubric_scores: Readonly<Record<string, RubricScoreItem>>;
  missed_items: readonly string[];
  strengths: readonly string[];
  reasoning_errors: readonly string[];
  next_recommendations: readonly string[];
  source_references: readonly string[];
  source_reference_items?: readonly SourceReferenceItem[];
  explanation_source_items?: readonly ExplanationSourceItem[];
  knowledge_recommendations?: readonly KnowledgeRecommendationItem[];
  llm_reasoning_feedback?: readonly LlmReasoningFeedbackItem[];
  evidence_graph_summary?: EvidenceGraphSummary | null;
  training_progress_snapshot?: ReportTrainingProgressSnapshot | null;
  ai_reflection_review?: Partial<AiReflectionReview>;
  personal_skill_candidate?: Partial<PersonalTrainingSkillCandidate>;
  feedback_summary: string;
}>;

export type FeedbackReport = FeedbackReportPayload &
  Readonly<{
    source_reference_items: readonly SourceReferenceItem[];
    explanation_source_items: readonly ExplanationSourceItem[];
    knowledge_recommendations: readonly KnowledgeRecommendationItem[];
    llm_reasoning_feedback: readonly LlmReasoningFeedbackItem[];
    evidence_graph_summary: EvidenceGraphSummary | null;
    training_progress_snapshot: ReportTrainingProgressSnapshot | null;
    ai_reflection_review: AiReflectionReview;
    personal_skill_candidate: PersonalTrainingSkillCandidate;
  }>;

export function normalizeFeedbackReport(report: FeedbackReportPayload): FeedbackReport {
  return {
    ...report,
    source_reference_items: report.source_reference_items ?? [],
    explanation_source_items: report.explanation_source_items ?? [],
    knowledge_recommendations: report.knowledge_recommendations ?? [],
    llm_reasoning_feedback: report.llm_reasoning_feedback ?? [],
    evidence_graph_summary: report.evidence_graph_summary ?? null,
    training_progress_snapshot: report.training_progress_snapshot ?? null,
    ai_reflection_review: normalizeAiReflectionReview(report.ai_reflection_review),
    personal_skill_candidate: normalizePersonalTrainingSkillCandidate(report.personal_skill_candidate),
  };
}

function normalizeAiReflectionReview(review?: Partial<AiReflectionReview>): AiReflectionReview {
  return {
    ...DEFAULT_AI_REFLECTION_REVIEW,
    ...review,
    mistake_patterns: review?.mistake_patterns ?? [],
    source_references: review?.source_references ?? [],
    source_reference_items: review?.source_reference_items ?? [],
  };
}

function normalizePersonalTrainingSkillCandidate(candidate?: Partial<PersonalTrainingSkillCandidate>): PersonalTrainingSkillCandidate {
  return {
    ...DEFAULT_PERSONAL_TRAINING_SKILL_CANDIDATE,
    ...candidate,
    candidate_id: candidate?.candidate_id ?? null,
    skill_id: candidate?.skill_id ?? null,
    scope: candidate?.scope ?? "personal",
    rag_evidence_items: candidate?.rag_evidence_items ?? [],
    external_evidence_checks: candidate?.external_evidence_checks ?? [],
  };
}
