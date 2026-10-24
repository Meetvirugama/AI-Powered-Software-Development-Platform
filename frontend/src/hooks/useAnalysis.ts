/**
 * React Query mutation and state hooks for Week 2 Developer Intelligence.
 */

import { useMutation, type UseMutationOptions } from '@tanstack/react-query';
import { explainCode, detectBugs, generateTests } from '../services/analysis';
import type {
  ExplainCodeRequest,
  CodeExplanationResponse,
  BugDetectionRequest,
  BugDetectionResponse,
  TestGenerationRequest,
  TestGenerationResponse,
} from '../types/analysis';
import type { ApiError } from '../types/api';

/**
 * Hook to request an explanation for a repository target (file, symbol, or range).
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param options Optional React Query mutation options (e.g. onSuccess, onError).
 */
export function useExplainCode(
  repositoryId: string,
  options?: UseMutationOptions<CodeExplanationResponse, ApiError, ExplainCodeRequest>
) {
  return useMutation<CodeExplanationResponse, ApiError, ExplainCodeRequest>({
    mutationKey: ['explain-code', repositoryId],
    mutationFn: (payload: ExplainCodeRequest) => explainCode(repositoryId, payload),
    ...options,
  });
}

/**
 * Hook to detect bugs in a repository target (file, symbol, or range).
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param options Optional React Query mutation options (e.g. onSuccess, onError).
 */
export function useDetectBugs(
  repositoryId: string,
  options?: UseMutationOptions<BugDetectionResponse, ApiError, BugDetectionRequest>
) {
  return useMutation<BugDetectionResponse, ApiError, BugDetectionRequest>({
    mutationKey: ['detect-bugs', repositoryId],
    mutationFn: (payload: BugDetectionRequest) => detectBugs(repositoryId, payload),
    ...options,
  });
}

/**
 * Hook to generate framework-aware tests for a repository target (file, symbol, or range).
 *
 * @param repositoryId The UUID of the authorized repository.
 * @param options Optional React Query mutation options (e.g. onSuccess, onError).
 */
export function useGenerateTests(
  repositoryId: string,
  options?: UseMutationOptions<TestGenerationResponse, ApiError, TestGenerationRequest>
) {
  return useMutation<TestGenerationResponse, ApiError, TestGenerationRequest>({
    mutationKey: ['generate-tests', repositoryId],
    mutationFn: (payload: TestGenerationRequest) => generateTests(repositoryId, payload),
    ...options,
  });
}
