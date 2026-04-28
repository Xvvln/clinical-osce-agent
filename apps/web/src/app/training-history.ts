export type TrainingHistoryRecord = Readonly<{
  sessionId: string;
  caseId: string;
  caseTitle: string;
  totalScore: number;
  status: string;
  savedAt: string;
  reportUrl: string;
}>;

export const TRAINING_HISTORY_STORAGE_KEY = "clinical-osce-agent:training-history";

const MAX_TRAINING_HISTORY_RECORDS = 20;

function isTrainingHistoryRecord(value: unknown): value is TrainingHistoryRecord {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<Record<keyof TrainingHistoryRecord, unknown>>;
  return (
    typeof candidate.sessionId === "string" &&
    typeof candidate.caseId === "string" &&
    typeof candidate.caseTitle === "string" &&
    typeof candidate.totalScore === "number" &&
    typeof candidate.status === "string" &&
    typeof candidate.savedAt === "string" &&
    typeof candidate.reportUrl === "string"
  );
}

export function readTrainingHistoryRecords(): readonly TrainingHistoryRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  const rawHistory = window.localStorage.getItem(TRAINING_HISTORY_STORAGE_KEY);
  if (!rawHistory) {
    return [];
  }

  const parsedHistory: unknown = JSON.parse(rawHistory);
  if (!Array.isArray(parsedHistory)) {
    return [];
  }

  return parsedHistory.filter(isTrainingHistoryRecord);
}

export function saveTrainingHistoryRecord(record: TrainingHistoryRecord): readonly TrainingHistoryRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  const existingRecords = readTrainingHistoryRecords();
  const nextRecords = [
    record,
    ...existingRecords.filter((existingRecord) => existingRecord.sessionId !== record.sessionId),
  ].slice(0, MAX_TRAINING_HISTORY_RECORDS);
  window.localStorage.setItem(TRAINING_HISTORY_STORAGE_KEY, JSON.stringify(nextRecords));
  return nextRecords;
}

export function deleteTrainingHistoryRecord(sessionId: string): readonly TrainingHistoryRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  const nextRecords = readTrainingHistoryRecords().filter((record) => record.sessionId !== sessionId);
  if (nextRecords.length === 0) {
    window.localStorage.removeItem(TRAINING_HISTORY_STORAGE_KEY);
    return [];
  }

  window.localStorage.setItem(TRAINING_HISTORY_STORAGE_KEY, JSON.stringify(nextRecords));
  return nextRecords;
}

export function clearTrainingHistoryRecords(): readonly TrainingHistoryRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  window.localStorage.removeItem(TRAINING_HISTORY_STORAGE_KEY);
  return [];
}
