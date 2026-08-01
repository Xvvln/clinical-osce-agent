export type LearningPathTargetReference = Readonly<{
  case_id: string;
  item_id: string;
}>;

type LearningPathTargetTask = Readonly<{
  case_id: string;
  target_rubric_items: readonly string[];
  target_rubric_item_refs?: readonly LearningPathTargetReference[];
}>;

export function getLearningPathTargetKey(
  task: LearningPathTargetTask,
  itemLabel: string,
  index: number,
): string {
  const itemReference = task.target_rubric_item_refs?.[index];
  const sourceCaseId = itemReference?.case_id || task.case_id;
  const itemId = itemReference?.item_id || task.target_rubric_items[index] || itemLabel;
  return `${sourceCaseId}-${itemId}-${index}`;
}
