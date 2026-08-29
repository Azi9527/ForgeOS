import type { ProjectValidationRun } from "./types";

export function findProjectValidationCleanupQuarantine(runs: ProjectValidationRun[]) {
  return runs.find((run) => run.cleanupConfirmed === false && !run.cleanupAcknowledgedAt) ?? null;
}
