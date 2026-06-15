import {
  normalizeFeedbackReport,
  type AiReflectionReview,
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
} satisfies FeedbackReportPayload;

const normalizedLegacyReport = normalizeFeedbackReport(legacyReport);
const legacyLlmFeedbackItems: readonly LlmReasoningFeedbackItem[] = normalizedLegacyReport.llm_reasoning_feedback;
const legacyKnowledgeRecommendations: readonly KnowledgeRecommendationItem[] = normalizedLegacyReport.knowledge_recommendations;
const legacyAiReflectionReview: AiReflectionReview = normalizedLegacyReport.ai_reflection_review;
const legacyPersonalTrainingSkillCandidate: PersonalTrainingSkillCandidate = normalizedLegacyReport.personal_skill_candidate;
const normalizedNextReport = normalizeFeedbackReport(nextReport);
const nextKnowledgeRecommendations: readonly KnowledgeRecommendationItem[] = normalizedNextReport.knowledge_recommendations;
const nextSourceReferenceItems: readonly SourceReferenceItem[] = normalizedNextReport.source_reference_items;
const nextTrainingGap = normalizedNextReport.training_gaps[0];

void legacyLlmFeedbackItems;
void legacyKnowledgeRecommendations;
void legacyAiReflectionReview;
void legacyPersonalTrainingSkillCandidate;
void nextKnowledgeRecommendations;
void nextSourceReferenceItems;
void nextTrainingGap;
