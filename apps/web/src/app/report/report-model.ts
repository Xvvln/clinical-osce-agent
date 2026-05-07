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
  feedback_summary: string;
}>;

export type FeedbackReport = FeedbackReportPayload &
  Readonly<{
    source_reference_items: readonly SourceReferenceItem[];
    explanation_source_items: readonly ExplanationSourceItem[];
    knowledge_recommendations: readonly KnowledgeRecommendationItem[];
    llm_reasoning_feedback: readonly LlmReasoningFeedbackItem[];
    evidence_graph_summary: EvidenceGraphSummary | null;
  }>;

export function normalizeFeedbackReport(report: FeedbackReportPayload): FeedbackReport {
  return {
    ...report,
    source_reference_items: report.source_reference_items ?? [],
    explanation_source_items: report.explanation_source_items ?? [],
    knowledge_recommendations: report.knowledge_recommendations ?? [],
    llm_reasoning_feedback: report.llm_reasoning_feedback ?? [],
    evidence_graph_summary: report.evidence_graph_summary ?? null,
  };
}
