import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import type { TaskDetailResponse, TaskEvent } from "../types/task"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * GitHub App integration configuration and helper functions.
 */
export function getGitHubAppInstallationUrl(): string {
  const customUrl = import.meta.env.VITE_GITHUB_APP_INSTALLATION_URL
  if (customUrl && typeof customUrl === "string" && customUrl.trim()) {
    return customUrl.trim()
  }

  const appSlug = import.meta.env.VITE_GITHUB_APP_SLUG || "ai-dev-platform-local"
  return `https://github.com/apps/${appSlug}/installations/new`
}

/**
 * Resolves the decision's associated plan version using explicit precedence:
 * 1. event.details.plan_version
 * 2. task.approved_plan_version
 * 3. task.plan_version
 */
export function getDecisionPlanVersion(evt: TaskEvent, task: TaskDetailResponse): number | string {
  const detailVersion = evt.details?.plan_version
  if (typeof detailVersion === "number" && !Number.isNaN(detailVersion)) {
    return detailVersion
  }
  if (typeof detailVersion === "string" && detailVersion.trim() !== "") {
    const parsed = Number(detailVersion)
    if (!Number.isNaN(parsed)) {
      return parsed
    }
  }
  if (typeof task.approved_plan_version === "number") {
    return task.approved_plan_version
  }
  return task.plan_version
}
