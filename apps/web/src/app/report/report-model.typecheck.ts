import {
  normalizeFeedbackReport,
  type FeedbackReportPayload,
  type KnowledgeRecommendationItem,
  type LlmReasoningFeedbackItem,
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
const nextKnowledgeRecommendations: readonly KnowledgeRecommendationItem[] = normalizeFeedbackReport(nextReport).knowledge_recommendations;

void legacyLlmFeedbackItems;
void legacyKnowledgeRecommendations;
void nextKnowledgeRecommendations;
