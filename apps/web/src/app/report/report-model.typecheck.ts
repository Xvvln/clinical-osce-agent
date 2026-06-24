import {
  normalizeFeedbackReport,
  type AiReflectionReview,
  type DeepReportAnalysis,
  type FeedbackReportPayload,
  type KnowledgeRecommendationItem,
  type LlmReasoningFeedbackItem,
  type PersonalTrainingSkillCandidate,
  type SourceReferenceItem,
} from "./report-model";

const legacyReport = {
  session_id: "legacy_session",
  case_id: "appendicitis_001",
  total_score: 55,
  dimension_scores: {},
  rubric_scores: {},
  missed_items: [],
  strengths: [],
  reasoning_errors: [],
  next_recommendations: [],
  source_references: [],
  feedback_summary: "历史报告。",
} satisfies FeedbackReportPayload;

const nextReport = {
  ...legacyReport,
  score_groups: {
    clinical_osce: { score: 42, max_score: 70 },
    humanistic_communication: { score: 18, max_score: 30 },
  },
  dimension_traces: {
    medical_ethics: [
      {
        rubric_item_id: "eth_exam_consent",
        awarded_score: 1,
        max_score: 3,
        match_kind: "sequence_check",
        matched_evidence: ["刚才查腹部是为了判断压痛，可以吗？"],
        gap_type: "ethics_consent_missing",
        timing_status: "late",
      },
    ],
  },
  training_gaps: [
    {
      dimension_id: "medical_ethics",
      rubric_item_id: "eth_exam_consent",
      gap_type: "ethics_consent_missing",
      label: "查体或检查前说明目的并征得同意",
      missing_score: 2,
      severity: "high",
      evidence_summary: "相关表达发生在动作之后，不能作为事前沟通满分证据。",
      next_training_action: "下一轮查体或检查前先说明目的、可能不适并征得同意。",
      skill_type: "ethics_consent",
      gap_source: "score_trace",
    },
  ],
  missed_opportunities: [],
  source_reference_items: [
    {
      reference: "source:fareez_osce_2022",
      source_type: "source",
      title: "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases",
      metadata: {
        license: "CC BY 4.0",
        source_url: "https://doi.org/10.6084/m9.figshare.c.5545842.v1",
      },
    },
  ],
  knowledge_recommendations: [
    {
      reference: "knowledge:appendicitis_001.rp_03",
      title: "急性阑尾炎诊断依据",
      reason: "关联本轮缺失证据：白细胞升高支持急性炎症过程。",
    },
  ],
  deep_report_analysis: {
    version: "deep_report_analysis_v1",
    status: "generated",
    overall_evaluation: {
      summary: "本轮需要重建证据链。",
      score_interpretation: "本轮总分 28/100，临床 OSCE 24/70，人文沟通 4/30。",
      completion_judgement: "needs_rebuild",
      primary_strengths: ["病史采集完成度相对较高。"],
      primary_weaknesses: ["缺少腹部局部体征"],
    },
    diagnostic_contrast_analysis: {
      submitted_diagnosis: "急性胃肠炎",
      target_diagnosis: "急性阑尾炎",
      classification: "plausible_differential",
      matched_target_terms: [],
      matched_differential_name: "急性胃肠炎",
      why_student_may_choose_it: ["恶心可能让学生想到胃肠炎。"],
      evidence_supporting_submitted: [],
      evidence_against_submitted: [{ source_id: "appendicitis_001.hf_05", label: "没有明显腹泻" }],
      evidence_supporting_target: [{ source_id: "appendicitis_001.hf_02", label: "转移性右下腹痛" }],
      missed_discriminating_evidence: [{ source_id: "lab.urinalysis", label: "尿常规" }],
      reasoning_error_patterns: ["鉴别诊断过窄"],
      teacher_explanation: "这个诊断有一定诱因，但已有证据更支持阑尾炎。",
      next_training_action: "先列支持依据，再列反证 / 排除依据，最后提交诊断。",
    },
    clinical_task_analysis: {
      physical_exam: {
        task_id: "physical_exam",
        label: "查体",
        score: 0,
        max_score: 10,
        completion_level: "missing",
        completed_items: [],
        missed_items: [{ item_id: "pe_rebound", label: "检查反跳痛", score: 0, max_score: 4 }],
        next_action: "补充腹部局部体征。",
      },
    },
    evidence_utilization_analysis: {
      collected_key_evidence: [{ source_id: "appendicitis_001.hf_02", label: "转移性右下腹痛" }],
      missing_key_evidence: [{ source_id: "lab.urinalysis", label: "尿常规阴性" }],
      evidence_chain_breakpoints: [
        {
          breakpoint_id: "appendicitis_001.rp_05",
          statement: "尿常规阴性有助于排除输尿管结石。",
          kind: "exclude",
          status: "broken",
          missing_evidence: ["lab.urinalysis"],
          missing_evidence_labels: ["尿常规阴性"],
          teacher_action: "补齐尿常规。",
        },
      ],
      unused_or_misused_evidence: [],
    },
    process_strategy_analysis: {
      action_order_summary: "本轮过程顺序存在需要复盘的节点。",
      sequence_flags: [{ flag_id: "late_hypothesis", label: "诊断假设生成偏晚", severity: "medium", evidence: "提交前才形成明确假设" }],
      premature_or_delayed_actions: ["下一轮先形成诊断假设，再选择查体和检查。"],
    },
  },
} satisfies FeedbackReportPayload;

const normalizedLegacyReport = normalizeFeedbackReport(legacyReport);
const legacyLlmFeedbackItems: readonly LlmReasoningFeedbackItem[] = normalizedLegacyReport.llm_reasoning_feedback;
const legacyKnowledgeRecommendations: readonly KnowledgeRecommendationItem[] = normalizedLegacyReport.knowledge_recommendations;
const legacyAiReflectionReview: AiReflectionReview = normalizedLegacyReport.ai_reflection_review;
const legacyPersonalTrainingSkillCandidate: PersonalTrainingSkillCandidate = normalizedLegacyReport.personal_skill_candidate;
const legacyDeepReportAnalysis: DeepReportAnalysis = normalizedLegacyReport.deep_report_analysis;
const normalizedNextReport = normalizeFeedbackReport(nextReport);
const nextKnowledgeRecommendations: readonly KnowledgeRecommendationItem[] = normalizedNextReport.knowledge_recommendations;
const nextSourceReferenceItems: readonly SourceReferenceItem[] = normalizedNextReport.source_reference_items;
const nextTrainingGap = normalizedNextReport.training_gaps[0];
const nextDeepReportAnalysis: DeepReportAnalysis = normalizedNextReport.deep_report_analysis;
const nextDeepReportOverallSummary: string = normalizedNextReport.deep_report_analysis.overall_evaluation.summary;
const nextPhysicalExamTaskLabel: string = normalizedNextReport.deep_report_analysis.clinical_task_analysis.physical_exam.label;
const nextEvidenceBreakpointStatement: string =
  normalizedNextReport.deep_report_analysis.evidence_utilization_analysis.evidence_chain_breakpoints[0].statement;
const nextProcessAction: string = normalizedNextReport.deep_report_analysis.process_strategy_analysis.premature_or_delayed_actions[0];

void legacyLlmFeedbackItems;
void legacyKnowledgeRecommendations;
void legacyAiReflectionReview;
void legacyPersonalTrainingSkillCandidate;
void legacyDeepReportAnalysis;
void nextKnowledgeRecommendations;
void nextSourceReferenceItems;
void nextTrainingGap;
void nextDeepReportAnalysis;
void nextDeepReportOverallSummary;
void nextPhysicalExamTaskLabel;
void nextEvidenceBreakpointStatement;
void nextProcessAction;
