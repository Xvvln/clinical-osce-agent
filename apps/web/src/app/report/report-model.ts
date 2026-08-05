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

export type TeacherLongitudinalGapStatusCounts = Readonly<{
  first_seen_current_window: number;
  repeated: number;
  reactivated_after_improvement: number;
  recovered_since_previous_report: number;
}>;

export type TeacherLongitudinalContext = Readonly<{
  gap_status_counts: TeacherLongitudinalGapStatusCounts;
  applied_personal_skills: readonly Readonly<Record<string, unknown>>[];
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
  longitudinal_context: TeacherLongitudinalContext;
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
  longitudinal_context: {
    gap_status_counts: {
      first_seen_current_window: 0,
      repeated: 0,
      reactivated_after_improvement: 0,
      recovered_since_previous_report: 0,
    },
    applied_personal_skills: [],
  },
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

export type ReportHistoryProgress = Readonly<{
  total: number;
  covered: number;
  covered_fact_ids: readonly string[];
  pending_fact_ids: readonly string[];
}>;

export type ReportProcedureProgress = Readonly<{
  total: number;
  requested: number;
  requested_codes: readonly string[];
  pending_codes: readonly string[];
  must_total: number;
  must_requested: number;
  must_pending_codes: readonly string[];
}>;

export type ReportReasoningProgress = Readonly<{
  total_evidence: number;
  collected_evidence_count: number;
  collected_evidence: readonly string[];
  pending_evidence: readonly string[];
  ready_for_hypothesis: boolean;
}>;

export type ReportTrainingProgressSnapshot = Readonly<{
  coverage_map: ReportCoverageMapPayload;
  history?: ReportHistoryProgress;
  physical_exam?: ReportProcedureProgress;
  auxiliary_test?: ReportProcedureProgress;
  reasoning?: ReportReasoningProgress;
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

export type DiagnosticEvidenceItem = Readonly<{
  source_id: string;
  label: string;
  node_id?: string;
}>;

export type OverallEvaluation = Readonly<{
  summary: string;
  score_interpretation: string;
  completion_judgement: string;
  primary_strengths: readonly string[];
  primary_weaknesses: readonly string[];
}>;

export type ClinicalTaskTraceItem = Readonly<{
  item_id: string;
  label: string;
  score: number;
  max_score: number;
  gap_type?: string;
  next_training_action?: string;
}>;

export type ClinicalTaskAnalysisItem = Readonly<{
  task_id: string;
  label: string;
  score: number;
  max_score: number;
  completion_level: string;
  completed_items: readonly ClinicalTaskTraceItem[];
  missed_items: readonly ClinicalTaskTraceItem[];
  next_action: string;
}>;

export type EvidenceChainBreakpoint = Readonly<{
  breakpoint_id: string;
  statement: string;
  kind: string;
  status: string;
  missing_evidence: readonly string[];
  missing_evidence_labels: readonly string[];
  teacher_action: string;
}>;

export type MisusedEvidenceItem = Readonly<{
  source_id: string;
  label: string;
  issue: string;
  next_training_action: string;
}>;

export type EvidenceUtilizationAnalysis = Readonly<{
  collected_key_evidence: readonly DiagnosticEvidenceItem[];
  missing_key_evidence: readonly DiagnosticEvidenceItem[];
  evidence_chain_breakpoints: readonly EvidenceChainBreakpoint[];
  unused_or_misused_evidence: readonly MisusedEvidenceItem[];
}>;

export type ProcessSequenceFlag = Readonly<{
  flag_id: string;
  label: string;
  severity: string;
  evidence: string;
}>;

export type ProcessStrategyAnalysis = Readonly<{
  action_order_summary: string;
  sequence_flags: readonly ProcessSequenceFlag[];
  premature_or_delayed_actions: readonly string[];
}>;

export type HumanisticDimensionScore = Readonly<{
  dimension_id: string;
  label: string;
  score: number;
  max_score: number;
  completion_level: string;
}>;

export type HumanisticMatchedEvidence = Readonly<{
  dimension_id: string;
  dimension_label: string;
  rubric_item_id: string;
  label: string;
  score: number;
  max_score: number;
  stage: string;
  matched_evidence: readonly string[];
  match_method: string;
  timing_status: string;
}>;

export type HumanisticCommunicationAnalysis = Readonly<{
  dimension_scores: readonly HumanisticDimensionScore[];
  matched_evidence: readonly HumanisticMatchedEvidence[];
  missed_opportunities: readonly MissedOpportunityItem[];
  relationship_repair_actions: readonly string[];
}>;

export type NextTrainingGoal = Readonly<{
  gap_type: string;
  label: string;
  dimension_id: string;
  stage: string;
  priority: number;
  severity: string;
  trigger: string;
  next_training_action: string;
  success_signal: string;
  skill_type: string;
  gap_source: string;
}>;

export type StageTriggeredTrainingAction = Readonly<{
  stage: string;
  trigger: string;
  action: string;
  gap_type: string;
  success_signal: string;
}>;

export type LinkedTrainingGap = Readonly<{
  dimension_id: string;
  rubric_item_id: string;
  gap_type: string;
  label: string;
  missing_score: number;
  severity: string;
  stage: string;
  trigger_stage: string;
  next_training_action: string;
  skill_type: string;
  gap_source: string;
}>;

export type NextTrainingPlan = Readonly<{
  top_goals: readonly NextTrainingGoal[];
  stage_triggered_actions: readonly StageTriggeredTrainingAction[];
  success_signals: readonly string[];
  linked_training_gaps: readonly LinkedTrainingGap[];
}>;

export type DiagnosticContrastAnalysis = Readonly<{
  submitted_diagnosis: string;
  target_diagnosis: string;
  classification: string;
  matched_target_terms: readonly string[];
  matched_differential_name: string;
  why_student_may_choose_it: readonly string[];
  evidence_supporting_submitted: readonly DiagnosticEvidenceItem[];
  evidence_against_submitted: readonly DiagnosticEvidenceItem[];
  evidence_supporting_target: readonly DiagnosticEvidenceItem[];
  missed_discriminating_evidence: readonly DiagnosticEvidenceItem[];
  reasoning_error_patterns: readonly string[];
  teacher_explanation: string;
  next_training_action: string;
}>;

export type DeepReportAnalysis = Readonly<{
  version: string;
  status: string;
  overall_evaluation: OverallEvaluation;
  diagnostic_contrast_analysis: DiagnosticContrastAnalysis;
  clinical_task_analysis: Readonly<Record<string, ClinicalTaskAnalysisItem>>;
  evidence_utilization_analysis: EvidenceUtilizationAnalysis;
  process_strategy_analysis: ProcessStrategyAnalysis;
  humanistic_communication_analysis: HumanisticCommunicationAnalysis;
  next_training_plan: NextTrainingPlan;
}>;

export type StudentReportOutcome = Readonly<{
  summary: string;
  score_summary: string;
  diagnosis_status: "correct" | "plausible_differential" | "partially_correct" | "incorrect" | "unsupported" | "not_submitted";
  diagnosis_summary: string;
  safety_summary: string;
  communication_summary: string;
}>;

export type StudentDecisionReplay = Readonly<{
  replay_id: string;
  kind: "strength" | "reasoning" | "evidence" | "sequence" | "safety" | "humanistic";
  phase: string;
  title: string;
  observed_evidence: string;
  teacher_judgement: string;
  why_it_matters: string;
  next_action: string;
  evidence_labels: readonly string[];
}>;

export type StudentTrainingPrescription = Readonly<{
  goal_id: string;
  title: string;
  trigger: string;
  action: string;
  success_signal: string;
}>;

export type StudentLongitudinalSummary = Readonly<{
  status: "insufficient_history" | "first_seen" | "repeated" | "reactivated" | "improving";
  label: string;
  summary: string;
  first_seen_count: number;
  repeated_count: number;
  reactivated_count: number;
  temporarily_absent_count: number;
}>;

export type StudentTrainingReport = Readonly<{
  version: string;
  status: "generated" | "legacy_fallback";
  outcome: StudentReportOutcome;
  decision_replays: readonly StudentDecisionReplay[];
  training_prescriptions: readonly StudentTrainingPrescription[];
  longitudinal_summary: StudentLongitudinalSummary;
  personal_memory_summary: string;
}>;

type StudentTrainingReportPayload = Readonly<
  Partial<Omit<StudentTrainingReport, "outcome" | "decision_replays" | "training_prescriptions" | "longitudinal_summary">> & {
    outcome?: Partial<StudentReportOutcome>;
    decision_replays?: readonly Partial<StudentDecisionReplay>[];
    training_prescriptions?: readonly Partial<StudentTrainingPrescription>[];
    longitudinal_summary?: Partial<StudentLongitudinalSummary>;
  }
>;

type DeepReportAnalysisPayload = Readonly<
  Partial<
    Omit<
      DeepReportAnalysis,
      | "overall_evaluation"
      | "diagnostic_contrast_analysis"
      | "clinical_task_analysis"
      | "evidence_utilization_analysis"
      | "process_strategy_analysis"
      | "humanistic_communication_analysis"
      | "next_training_plan"
    >
  > & {
    overall_evaluation?: Partial<OverallEvaluation>;
    diagnostic_contrast_analysis?: Partial<DiagnosticContrastAnalysis>;
    clinical_task_analysis?: Readonly<Record<string, Partial<ClinicalTaskAnalysisItem>>>;
    evidence_utilization_analysis?: Partial<EvidenceUtilizationAnalysis>;
    process_strategy_analysis?: Partial<ProcessStrategyAnalysis>;
    humanistic_communication_analysis?: Partial<HumanisticCommunicationAnalysis>;
    next_training_plan?: Partial<NextTrainingPlan>;
  }
>;

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
  deep_report_analysis?: DeepReportAnalysisPayload;
  student_training_report?: StudentTrainingReportPayload;
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
    deep_report_analysis: DeepReportAnalysis;
    student_training_report: StudentTrainingReport;
  }>;

export function normalizeFeedbackReport(report: FeedbackReportPayload): FeedbackReport {
  return {
    ...report,
    source_reference_items: report.source_reference_items ?? [],
    explanation_source_items: report.explanation_source_items ?? [],
    procedure_simulation_audit_items: report.procedure_simulation_audit_items ?? [],
    score_groups: report.score_groups ?? {},
    dimension_traces: report.dimension_traces ?? {},
    training_gaps: deduplicateTrainingGaps(report.training_gaps ?? []),
    missed_opportunities: report.missed_opportunities ?? [],
    knowledge_recommendations: report.knowledge_recommendations ?? [],
    llm_reasoning_feedback: report.llm_reasoning_feedback ?? [],
    evidence_graph_summary: report.evidence_graph_summary ?? null,
    training_progress_snapshot: report.training_progress_snapshot ?? null,
    ai_reflection_review: normalizeAiReflectionReview(report.ai_reflection_review),
    personal_skill_candidate: normalizePersonalTrainingSkillCandidate(report.personal_skill_candidate),
    deep_report_analysis: normalizeDeepReportAnalysis(report.deep_report_analysis),
    student_training_report: normalizeStudentTrainingReport(report),
  };
}

function deduplicateTrainingGaps(gaps: readonly TrainingGapItem[]): readonly TrainingGapItem[] {
  const seen = new Set<string>();
  return gaps.filter((gap) => {
    const identity = [
      gap.dimension_id,
      gap.rubric_item_id,
      gap.gap_type,
      gap.gap_source,
      gap.next_training_action,
    ].join("\u001f");
    if (seen.has(identity)) {
      return false;
    }
    seen.add(identity);
    return true;
  });
}

const DEFAULT_DIAGNOSTIC_CONTRAST_ANALYSIS: DiagnosticContrastAnalysis = {
  submitted_diagnosis: "",
  target_diagnosis: "",
  classification: "unsupported",
  matched_target_terms: [],
  matched_differential_name: "",
  why_student_may_choose_it: [],
  evidence_supporting_submitted: [],
  evidence_against_submitted: [],
  evidence_supporting_target: [],
  missed_discriminating_evidence: [],
  reasoning_error_patterns: [],
  teacher_explanation: "",
  next_training_action: "",
};

const DEFAULT_OVERALL_EVALUATION: OverallEvaluation = {
  summary: "",
  score_interpretation: "",
  completion_judgement: "not_ready",
  primary_strengths: [],
  primary_weaknesses: [],
};

const DEFAULT_EVIDENCE_UTILIZATION_ANALYSIS: EvidenceUtilizationAnalysis = {
  collected_key_evidence: [],
  missing_key_evidence: [],
  evidence_chain_breakpoints: [],
  unused_or_misused_evidence: [],
};

const DEFAULT_PROCESS_STRATEGY_ANALYSIS: ProcessStrategyAnalysis = {
  action_order_summary: "",
  sequence_flags: [],
  premature_or_delayed_actions: [],
};

const DEFAULT_HUMANISTIC_COMMUNICATION_ANALYSIS: HumanisticCommunicationAnalysis = {
  dimension_scores: [],
  matched_evidence: [],
  missed_opportunities: [],
  relationship_repair_actions: [],
};

const DEFAULT_NEXT_TRAINING_PLAN: NextTrainingPlan = {
  top_goals: [],
  stage_triggered_actions: [],
  success_signals: [],
  linked_training_gaps: [],
};

const DEFAULT_DEEP_REPORT_ANALYSIS: DeepReportAnalysis = {
  version: "deep_report_analysis_v1",
  status: "legacy_report",
  overall_evaluation: DEFAULT_OVERALL_EVALUATION,
  diagnostic_contrast_analysis: DEFAULT_DIAGNOSTIC_CONTRAST_ANALYSIS,
  clinical_task_analysis: {},
  evidence_utilization_analysis: DEFAULT_EVIDENCE_UTILIZATION_ANALYSIS,
  process_strategy_analysis: DEFAULT_PROCESS_STRATEGY_ANALYSIS,
  humanistic_communication_analysis: DEFAULT_HUMANISTIC_COMMUNICATION_ANALYSIS,
  next_training_plan: DEFAULT_NEXT_TRAINING_PLAN,
};

function normalizeDeepReportAnalysis(analysis?: DeepReportAnalysisPayload): DeepReportAnalysis {
  const overall = analysis?.overall_evaluation ?? {};
  const diagnosticContrast = analysis?.diagnostic_contrast_analysis ?? {};
  const evidenceUtilization = analysis?.evidence_utilization_analysis ?? {};
  const processStrategy = analysis?.process_strategy_analysis ?? {};
  const humanisticCommunication = analysis?.humanistic_communication_analysis ?? {};
  const nextTrainingPlan = analysis?.next_training_plan ?? {};
  return {
    ...DEFAULT_DEEP_REPORT_ANALYSIS,
    ...analysis,
    overall_evaluation: {
      ...DEFAULT_OVERALL_EVALUATION,
      ...overall,
      primary_strengths: overall.primary_strengths ?? [],
      primary_weaknesses: overall.primary_weaknesses ?? [],
    },
    diagnostic_contrast_analysis: {
      ...DEFAULT_DIAGNOSTIC_CONTRAST_ANALYSIS,
      ...diagnosticContrast,
      matched_target_terms: diagnosticContrast.matched_target_terms ?? [],
      why_student_may_choose_it: diagnosticContrast.why_student_may_choose_it ?? [],
      evidence_supporting_submitted: diagnosticContrast.evidence_supporting_submitted ?? [],
      evidence_against_submitted: diagnosticContrast.evidence_against_submitted ?? [],
      evidence_supporting_target: diagnosticContrast.evidence_supporting_target ?? [],
      missed_discriminating_evidence: diagnosticContrast.missed_discriminating_evidence ?? [],
      reasoning_error_patterns: diagnosticContrast.reasoning_error_patterns ?? [],
    },
    clinical_task_analysis: normalizeClinicalTaskAnalysis(analysis?.clinical_task_analysis),
    evidence_utilization_analysis: {
      ...DEFAULT_EVIDENCE_UTILIZATION_ANALYSIS,
      ...evidenceUtilization,
      collected_key_evidence: evidenceUtilization.collected_key_evidence ?? [],
      missing_key_evidence: evidenceUtilization.missing_key_evidence ?? [],
      evidence_chain_breakpoints: (evidenceUtilization.evidence_chain_breakpoints ?? []).map((item) => ({
        ...item,
        missing_evidence: item.missing_evidence ?? [],
        missing_evidence_labels: item.missing_evidence_labels ?? [],
      })),
      unused_or_misused_evidence: evidenceUtilization.unused_or_misused_evidence ?? [],
    },
    process_strategy_analysis: {
      ...DEFAULT_PROCESS_STRATEGY_ANALYSIS,
      ...processStrategy,
      sequence_flags: processStrategy.sequence_flags ?? [],
      premature_or_delayed_actions: processStrategy.premature_or_delayed_actions ?? [],
    },
    humanistic_communication_analysis: {
      ...DEFAULT_HUMANISTIC_COMMUNICATION_ANALYSIS,
      ...humanisticCommunication,
      dimension_scores: humanisticCommunication.dimension_scores ?? [],
      matched_evidence: (humanisticCommunication.matched_evidence ?? []).map((item) => ({
        ...item,
        matched_evidence: item.matched_evidence ?? [],
      })),
      missed_opportunities: humanisticCommunication.missed_opportunities ?? [],
      relationship_repair_actions: humanisticCommunication.relationship_repair_actions ?? [],
    },
    next_training_plan: {
      ...DEFAULT_NEXT_TRAINING_PLAN,
      ...nextTrainingPlan,
      top_goals: nextTrainingPlan.top_goals ?? [],
      stage_triggered_actions: nextTrainingPlan.stage_triggered_actions ?? [],
      success_signals: nextTrainingPlan.success_signals ?? [],
      linked_training_gaps: nextTrainingPlan.linked_training_gaps ?? [],
    },
  };
}

const STUDENT_VISIBLE_UUID_PATTERN = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i;
const STUDENT_VISIBLE_INTERNAL_TOKEN_PATTERN = /\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/;

function normalizeStudentTrainingReport(report: FeedbackReportPayload): StudentTrainingReport {
  const payload = report.student_training_report;
  const deepAnalysis = report.deep_report_analysis;
  const diagnostic = deepAnalysis?.diagnostic_contrast_analysis;
  const outcome = payload?.outcome;
  const diagnosisStatus = normalizeDiagnosisStatus(outcome?.diagnosis_status ?? diagnostic?.classification);
  const fallbackDecisionReplays = buildLegacyDecisionReplays(report);
  const fallbackPrescriptions = buildLegacyTrainingPrescriptions(report);
  const longitudinal = payload?.longitudinal_summary;
  return {
    version: payload?.version ?? "student_training_report_v2",
    status: payload?.status === "generated" ? "generated" : "legacy_fallback",
    outcome: {
      summary: normalizeStudentFacingText(outcome?.summary, report.feedback_summary || "本轮报告已生成，请优先查看关键决策和下一轮动作。"),
      score_summary: normalizeStudentFacingText(outcome?.score_summary, `本轮总分 ${report.total_score}/100。`),
      diagnosis_status: diagnosisStatus,
      diagnosis_summary: normalizeStudentFacingText(outcome?.diagnosis_summary, getLegacyDiagnosisSummary(diagnosisStatus)),
      safety_summary: normalizeStudentFacingText(outcome?.safety_summary, "本轮未记录明确的安全结论，请结合关键决策和评分明细复核。"),
      communication_summary: normalizeStudentFacingText(outcome?.communication_summary, "本轮沟通表现请结合关键决策和评分明细复核。"),
    },
    decision_replays: (payload?.decision_replays ?? fallbackDecisionReplays).slice(0, 3).map((item, index) => ({
      replay_id: item.replay_id ?? `decision-${index + 1}`,
      kind: normalizeDecisionReplayKind(item.kind),
      phase: normalizeStudentFacingText(item.phase, "本轮训练"),
      title: normalizeStudentFacingText(item.title, "关键训练动作"),
      observed_evidence: normalizeStudentFacingText(item.observed_evidence, "本轮评分轨迹尚未记录更具体的可见证据。"),
      teacher_judgement: normalizeStudentFacingText(item.teacher_judgement, "该动作需要在下一轮继续验证。"),
      why_it_matters: normalizeStudentFacingText(item.why_it_matters, "临床训练需要让每个结论都能回到可观察的问诊、操作或推理证据。"),
      next_action: normalizeStudentFacingText(item.next_action, "下一轮主动完成该动作，并说明它如何影响判断。"),
      evidence_labels: (item.evidence_labels ?? []).map((label) => normalizeStudentFacingText(label, "训练证据")).slice(0, 6),
    })),
    training_prescriptions: (payload?.training_prescriptions ?? fallbackPrescriptions).slice(0, 3).map((item, index) => ({
      goal_id: item.goal_id ?? `goal-${index + 1}`,
      title: normalizeStudentFacingText(item.title, "完成下一轮关键动作"),
      trigger: normalizeStudentFacingText(item.trigger, "进入下一轮相似训练场景时"),
      action: normalizeStudentFacingText(item.action, "主动完成该训练动作，并说明目的。"),
      success_signal: normalizeStudentFacingText(item.success_signal, "评分轨迹能够找到对应动作和推理表达。"),
    })),
    longitudinal_summary: {
      status: normalizeLongitudinalStatus(longitudinal?.status),
      label: normalizeStudentFacingText(longitudinal?.label, "历史不足"),
      summary: normalizeStudentFacingText(longitudinal?.summary, "当前缺少足够的可比较训练记录，暂不能判断问题是偶发还是反复。"),
      first_seen_count: normalizeNonNegativeCount(longitudinal?.first_seen_count),
      repeated_count: normalizeNonNegativeCount(longitudinal?.repeated_count),
      reactivated_count: normalizeNonNegativeCount(longitudinal?.reactivated_count),
      temporarily_absent_count: normalizeNonNegativeCount(longitudinal?.temporarily_absent_count),
    },
    personal_memory_summary: normalizeStudentFacingText(
      payload?.personal_memory_summary,
      "系统尚未形成可复用的个人训练策略，本轮结论仍可直接用于下一次练习。",
    ),
  };
}

function buildLegacyDecisionReplays(report: FeedbackReportPayload): readonly Partial<StudentDecisionReplay>[] {
  const strength = report.strengths.find((item) => Boolean(normalizeStudentFacingText(item, "")));
  const gaps = (report.training_gaps ?? []).slice(0, strength ? 2 : 3);
  const items: Partial<StudentDecisionReplay>[] = [];
  if (strength) {
    items.push({
      kind: "strength",
      phase: "本轮训练",
      title: "本轮有效做法",
      observed_evidence: strength,
      teacher_judgement: "这是本轮已经形成的有效动作，下一轮应继续保留。",
      why_it_matters: "稳定复现有效动作，才能判断能力是否真正迁移到新病例。",
      next_action: "下一轮在新病例中再次独立完成，并说明该动作支持或排除什么。",
      evidence_labels: [strength],
    });
  }
  for (const gap of gaps) {
    items.push({
      kind: "evidence",
      phase: "临床推理",
      title: gap.label,
      observed_evidence: gap.evidence_summary || `评分轨迹没有找到足够证据证明你完成了“${gap.label}”。`,
      teacher_judgement: "该训练点目前还没有形成稳定、可观察的完成证据。",
      why_it_matters: "评分依据关注可观察的问诊、操作和推理表达，不能只依赖最终结论。",
      next_action: gap.next_training_action || `下一轮主动完成“${gap.label}”，并说明它如何影响判断。`,
      evidence_labels: [gap.label],
    });
  }
  return items.length > 0 ? items : [{
    kind: "strength",
    phase: "本轮训练",
    title: "完成了一轮完整训练",
    observed_evidence: "系统已保存本轮训练轨迹。",
    teacher_judgement: "当前材料可用于下一轮迁移练习。",
    why_it_matters: "完整训练轨迹让后续反馈能够对应到具体动作。",
    next_action: "下一轮继续完成完整流程，并主动说明每一步的目的。",
    evidence_labels: ["完整训练记录"],
  }];
}

function buildLegacyTrainingPrescriptions(report: FeedbackReportPayload): readonly Partial<StudentTrainingPrescription>[] {
  const actions = report.next_recommendations.map((action, index) => ({
    goal_id: `legacy-goal-${index + 1}`,
    title: "执行下一轮训练动作",
    trigger: "下一轮遇到相似临床任务时",
    action,
    success_signal: "能够不依赖提示完成该动作，并说出它将验证或排除什么。",
  }));
  return actions.length > 0 ? actions : [{
    goal_id: "legacy-goal-1",
    title: "迁移本轮有效做法",
    trigger: "进入下一个新病例时",
    action: "独立完成问诊、关键查体、必要检查和诊断推理，并说明每一步的目的。",
    success_signal: "能够形成完整证据链，且不新增明显安全或沟通问题。",
  }];
}

function normalizeStudentFacingText(value: unknown, fallback: string): string {
  const normalized = typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
  if (!normalized || STUDENT_VISIBLE_UUID_PATTERN.test(normalized) || STUDENT_VISIBLE_INTERNAL_TOKEN_PATTERN.test(normalized)) {
    return fallback;
  }
  if (/^[\x00-\x7F]+$/.test(normalized) && !/\d/.test(normalized)) {
    return fallback;
  }
  return normalized;
}

function normalizeDiagnosisStatus(value: unknown): StudentReportOutcome["diagnosis_status"] {
  return value === "correct" || value === "plausible_differential" || value === "partially_correct" || value === "incorrect" || value === "not_submitted"
    ? value
    : "unsupported";
}

function getLegacyDiagnosisSummary(status: StudentReportOutcome["diagnosis_status"]): string {
  if (status === "correct") {
    return "主诊断与病例目标一致。";
  }
  if (status === "plausible_differential") {
    return "提交内容更接近合理鉴别诊断，但尚未命中主要诊断。";
  }
  if (status === "partially_correct") {
    return "诊断方向部分接近病例目标，但表达或证据仍不完整。";
  }
  if (status === "incorrect") {
    return "主诊断与病例目标不一致。";
  }
  if (status === "not_submitted") {
    return "本轮尚未提交诊断。";
  }
  return "现有证据不足以支持提交的诊断。";
}

function normalizeDecisionReplayKind(value: unknown): StudentDecisionReplay["kind"] {
  return value === "strength" || value === "reasoning" || value === "sequence" || value === "safety" || value === "humanistic"
    ? value
    : "evidence";
}

function normalizeLongitudinalStatus(value: unknown): StudentLongitudinalSummary["status"] {
  return value === "first_seen" || value === "repeated" || value === "reactivated" || value === "improving"
    ? value
    : "insufficient_history";
}

function normalizeClinicalTaskAnalysis(
  analysis?: Readonly<Record<string, Partial<ClinicalTaskAnalysisItem>>>,
): Readonly<Record<string, ClinicalTaskAnalysisItem>> {
  if (!analysis) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(analysis).map(([taskId, item]) => [
      taskId,
      {
        task_id: item.task_id ?? taskId,
        label: item.label ?? taskId,
        score: item.score ?? 0,
        max_score: item.max_score ?? 0,
        completion_level: item.completion_level ?? "missing",
        completed_items: item.completed_items ?? [],
        missed_items: item.missed_items ?? [],
        next_action: item.next_action ?? "",
      },
    ]),
  );
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
  const longitudinalContext = context?.longitudinal_context;
  const gapStatusCounts = longitudinalContext?.gap_status_counts;
  return {
    ...DEFAULT_TEACHER_ANALYSIS_CONTEXT,
    ...context,
    clinical_thinking_profile: context?.clinical_thinking_profile ?? {},
    major_issue_titles: context?.major_issue_titles ?? [],
    skill_memory_focus: context?.skill_memory_focus ?? {},
    source_anchor_labels: context?.source_anchor_labels ?? [],
    longitudinal_context: {
      gap_status_counts: {
        first_seen_current_window: normalizeNonNegativeCount(gapStatusCounts?.first_seen_current_window),
        repeated: normalizeNonNegativeCount(gapStatusCounts?.repeated),
        reactivated_after_improvement: normalizeNonNegativeCount(gapStatusCounts?.reactivated_after_improvement),
        recovered_since_previous_report: normalizeNonNegativeCount(gapStatusCounts?.recovered_since_previous_report),
      },
      applied_personal_skills: longitudinalContext?.applied_personal_skills ?? [],
    },
  };
}

function normalizeNonNegativeCount(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
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
