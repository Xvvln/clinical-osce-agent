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

export type ProcedureSimulationAuditItem = Readonly<{
  procedure_id: string;
  kind: string;
  code: string;
  label: string;
  result: string;
  approval_status: string;
  approval_agent_review?: Readonly<Record<string, unknown>>;
  source_context_references: readonly string[];
  scoring_eligible: boolean;
  safety_boundary: string;
}>;

export type TeacherReflectionMajorIssue = Readonly<{
  title: string;
  observed_behavior: string;
  why_it_matters: string;
  correct_approach: string;
  next_action: string;
  linked_items: readonly string[];
}>;

export type TeacherCoachingReviewSection = Readonly<{
  section_id: string;
  title: string;
  teacher_comment: string;
  why_it_matters: string;
  next_move: string;
  evidence_labels: readonly string[];
}>;

export type TeacherReasoningSequenceFlag = Readonly<{
  flag_id: string;
  label: string;
  severity: string;
  evidence: string;
}>;

export type TeacherActionOrderSummary = Readonly<{
  first_history_turn_index: number | null;
  first_physical_exam_turn_index: number | null;
  first_auxiliary_test_turn_index: number | null;
  first_diagnosis_hypothesis_turn_index: number | null;
  diagnosis_submission_turn_index: number | null;
}>;

export type TeacherEvidenceChainBreakpoint = Readonly<{
  breakpoint_id: string;
  statement: string;
  kind: string;
  status: string;
  missing_evidence: readonly string[];
  missing_evidence_labels: readonly string[];
  teacher_action: string;
}>;

export type TeacherReasoningTraceSummary = Readonly<{
  trace_version: string;
  dominant_patterns: readonly Readonly<Record<string, string>>[];
  problem_representation_status: string;
  illness_script_status: string;
  evidence_synthesis_status: string;
  sequence_flags: readonly TeacherReasoningSequenceFlag[];
  action_order_summary: TeacherActionOrderSummary;
  evidence_chain_breakpoints: readonly TeacherEvidenceChainBreakpoint[];
  evidence_chain_focus: readonly Readonly<Record<string, unknown>>[];
}>;

export type TeacherAnalysisContext = Readonly<{
  agent_id: string;
  analysis_mode: string;
  analysis_summary: string;
  student_thinking_hypothesis: string;
  clinical_thinking_profile: Readonly<Record<string, unknown>>;
  major_issue_titles: readonly string[];
  skill_memory_focus: Readonly<Record<string, unknown>>;
  source_anchor_labels: readonly string[];
  teaching_prompt_version?: string;
}>;

export type AiReflectionReview = Readonly<{
  status: string;
  reason?: string;
  summary: string;
  overall_comment: string;
  strengths_review: readonly string[];
  major_issues: readonly TeacherReflectionMajorIssue[];
  teacher_coaching_review: readonly TeacherCoachingReviewSection[];
  reasoning_chain_review: string;
  next_practice_plan: readonly string[];
  teacher_note: string;
  mistake_patterns: readonly string[];
  teacher_feedback: string;
  next_focus: string;
  reasoning_trace_summary: TeacherReasoningTraceSummary;
  source_references: readonly string[];
  source_reference_items: readonly SourceReferenceItem[];
  teacher_analysis_context: TeacherAnalysisContext;
  generated_by?: string;
  teaching_prompt_version?: string;
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
  teacher_analysis_context: TeacherAnalysisContext;
  rag_evidence_items: readonly SourceReferenceItem[];
  web_check_status: string;
  external_evidence_checks: readonly unknown[];
}>;

export const DEFAULT_TEACHER_ANALYSIS_CONTEXT: TeacherAnalysisContext = {
  agent_id: "",
  analysis_mode: "",
  analysis_summary: "",
  student_thinking_hypothesis: "",
  clinical_thinking_profile: {},
  major_issue_titles: [],
  skill_memory_focus: {},
  source_anchor_labels: [],
};

export const DEFAULT_REASONING_TRACE_SUMMARY: TeacherReasoningTraceSummary = {
  trace_version: "",
  dominant_patterns: [],
  problem_representation_status: "",
  illness_script_status: "",
  evidence_synthesis_status: "",
  sequence_flags: [],
  action_order_summary: {
    first_history_turn_index: null,
    first_physical_exam_turn_index: null,
    first_auxiliary_test_turn_index: null,
    first_diagnosis_hypothesis_turn_index: null,
    diagnosis_submission_turn_index: null,
  },
  evidence_chain_breakpoints: [],
  evidence_chain_focus: [],
};

export const DEFAULT_AI_REFLECTION_REVIEW: AiReflectionReview = {
  status: "legacy_report",
  reason: "ai_reflection_not_recorded",
  summary: "该历史报告生成时尚未记录教师复盘。",
  overall_comment: "",
  strengths_review: [],
  major_issues: [],
  teacher_coaching_review: [],
  reasoning_chain_review: "",
  next_practice_plan: [],
  teacher_note: "",
  mistake_patterns: [],
  teacher_feedback: "",
  next_focus: "",
  reasoning_trace_summary: DEFAULT_REASONING_TRACE_SUMMARY,
  source_references: [],
  source_reference_items: [],
  teacher_analysis_context: DEFAULT_TEACHER_ANALYSIS_CONTEXT,
};

export const DEFAULT_PERSONAL_TRAINING_SKILL_CANDIDATE: PersonalTrainingSkillCandidate = {
  status: "legacy_report",
  reason: "personal_skill_not_recorded",
  candidate_id: null,
  skill_id: null,
  scope: "personal",
  teacher_analysis_context: DEFAULT_TEACHER_ANALYSIS_CONTEXT,
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

export type ReportScoreGroup = Readonly<{
  score: number;
  max_score: number;
}>;

export type ReportScoreTrace = Readonly<{
  rubric_item_id: string;
  awarded_score: number;
  max_score: number;
  match_kind: string;
  matched_evidence: readonly string[];
  gap_type?: string;
  stage?: string;
  next_training_action?: string;
  match_method?: string;
  semantic_score?: number;
  timing_status?: string;
  llm_review_status?: string;
  ethics_principle?: string;
}>;

export type TrainingGapItem = Readonly<{
  dimension_id: string;
  rubric_item_id: string;
  gap_type: string;
  label: string;
  missing_score: number;
  severity: string;
  evidence_summary: string;
  next_training_action: string;
  skill_type: string;
  gap_source: string;
}>;

export type MissedOpportunityItem = Readonly<{
  opportunity_id: string;
  gap_type: string;
  stage: string;
  trigger_evidence: string;
  expected_response: string;
  next_training_action: string;
}>;

export type FeedbackReportPayload = Readonly<{
  session_id: string;
  case_id: string;
  total_score: number;
  dimension_scores: Readonly<Record<string, number>>;
  score_groups?: Readonly<Record<string, ReportScoreGroup>>;
  dimension_traces?: Readonly<Record<string, readonly ReportScoreTrace[]>>;
  rubric_scores: Readonly<Record<string, RubricScoreItem>>;
  missed_items: readonly string[];
  training_gaps?: readonly TrainingGapItem[];
  missed_opportunities?: readonly MissedOpportunityItem[];
  strengths: readonly string[];
  reasoning_errors: readonly string[];
  next_recommendations: readonly string[];
  source_references: readonly string[];
  source_reference_items?: readonly SourceReferenceItem[];
  explanation_source_items?: readonly ExplanationSourceItem[];
  procedure_simulation_audit_items?: readonly ProcedureSimulationAuditItem[];
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
    procedure_simulation_audit_items: readonly ProcedureSimulationAuditItem[];
    score_groups: Readonly<Record<string, ReportScoreGroup>>;
    dimension_traces: Readonly<Record<string, readonly ReportScoreTrace[]>>;
    training_gaps: readonly TrainingGapItem[];
    missed_opportunities: readonly MissedOpportunityItem[];
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
    procedure_simulation_audit_items: report.procedure_simulation_audit_items ?? [],
    score_groups: report.score_groups ?? {},
    dimension_traces: report.dimension_traces ?? {},
    training_gaps: report.training_gaps ?? [],
    missed_opportunities: report.missed_opportunities ?? [],
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
    strengths_review: review?.strengths_review ?? [],
    major_issues: review?.major_issues ?? [],
    teacher_coaching_review: review?.teacher_coaching_review ?? [],
    next_practice_plan: review?.next_practice_plan ?? [],
    mistake_patterns: review?.mistake_patterns ?? [],
    reasoning_trace_summary: normalizeTeacherReasoningTraceSummary(review?.reasoning_trace_summary),
    source_references: review?.source_references ?? [],
    source_reference_items: review?.source_reference_items ?? [],
    teacher_analysis_context: normalizeTeacherAnalysisContext(review?.teacher_analysis_context),
  };
}

function normalizeTeacherAnalysisContext(context?: Partial<TeacherAnalysisContext>): TeacherAnalysisContext {
  return {
    ...DEFAULT_TEACHER_ANALYSIS_CONTEXT,
    ...context,
    clinical_thinking_profile: context?.clinical_thinking_profile ?? {},
    major_issue_titles: context?.major_issue_titles ?? [],
    skill_memory_focus: context?.skill_memory_focus ?? {},
    source_anchor_labels: context?.source_anchor_labels ?? [],
  };
}

function normalizeTeacherReasoningTraceSummary(summary?: Partial<TeacherReasoningTraceSummary>): TeacherReasoningTraceSummary {
  return {
    ...DEFAULT_REASONING_TRACE_SUMMARY,
    ...summary,
    dominant_patterns: summary?.dominant_patterns ?? [],
    sequence_flags: summary?.sequence_flags ?? [],
    action_order_summary: {
      ...DEFAULT_REASONING_TRACE_SUMMARY.action_order_summary,
      ...(summary?.action_order_summary ?? {}),
    },
    evidence_chain_breakpoints: summary?.evidence_chain_breakpoints ?? [],
    evidence_chain_focus: summary?.evidence_chain_focus ?? [],
  };
}

function normalizePersonalTrainingSkillCandidate(candidate?: Partial<PersonalTrainingSkillCandidate>): PersonalTrainingSkillCandidate {
  return {
    ...DEFAULT_PERSONAL_TRAINING_SKILL_CANDIDATE,
    ...candidate,
    candidate_id: candidate?.candidate_id ?? null,
    skill_id: candidate?.skill_id ?? null,
    scope: candidate?.scope ?? "personal",
    teacher_analysis_context: normalizeTeacherAnalysisContext(candidate?.teacher_analysis_context),
    rag_evidence_items: candidate?.rag_evidence_items ?? [],
    external_evidence_checks: candidate?.external_evidence_checks ?? [],
  };
}
