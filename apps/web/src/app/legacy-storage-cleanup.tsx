"use client";

import { useEffect } from "react";
import { clearTrainingHistoryRecords } from "./training-history";

export function LegacyStorageCleanup() {
  useEffect(() => {
    clearTrainingHistoryRecords();
  }, []);

  return null;
}
