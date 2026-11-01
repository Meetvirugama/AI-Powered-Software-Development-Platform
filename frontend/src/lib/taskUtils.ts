import type { TaskDetailResponse, TaskEvent } from '../types/task';

/**
 * Resolves the decision's associated plan version using explicit precedence:
 * 1. event.details.plan_version
 * 2. task.approved_plan_version
 * 3. task.plan_version
 */
export function getDecisionPlanVersion(evt: TaskEvent, task: TaskDetailResponse): number | string {
  const detailVersion = evt.details?.plan_version;
  if (typeof detailVersion === 'number' && !Number.isNaN(detailVersion)) {
    return detailVersion;
  }
  if (typeof detailVersion === 'string' && detailVersion.trim() !== '') {
    const parsed = Number(detailVersion);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  if (typeof task.approved_plan_version === 'number') {
    return task.approved_plan_version;
  }
  return task.plan_version;
}
