/**
 * React Query mutation and state hooks for Week 2 Developer Intelligence.
 */

import { useState } from 'react';
import { useMutation, useQuery, type UseMutationOptions } from '@tanstack/react-query';
import {
  explainCode,
  detectBugs,
  generateTests,
  reviewCode,
  getRelatedFiles,
  streamExplainCode,
  streamDetectBugs,
  streamGenerateTests,
  streamReviewCode,
  AnalysisStreamUnavailableError,
  type AnalysisStageEvent,
  type AnalysisStreamHandlers,
} from '../services/analysis';
import type {
  ExplainCodeRequest,
  CodeExplanationResponse,
  RelatedFilesDiscoveryResponse,
  BugDetectionRequest,
  BugDetectionResponse,
  TestGenerationRequest,
  TestGenerationResponse,
  CodeReviewRequest,
  ReviewReportResponse,
} from '../types/analysis';
import type { ApiError } from '../types/api';

function useStreamingAnalysisMutation<TData, TVariables>(
  mutationKey: readonly unknown[],
  streamFn: (payload: TVariables, handlers: AnalysisStreamHandlers) => Promise<TData>,
  fallbackFn: (payload: TVariables) => Promise<TData>,
  options?: UseMutationOptions<TData, ApiError, TVariables>,
) {
  const [stageEvent, setStageEvent] = useState<AnalysisStageEvent | null>(null);
  const { onSettled, ...restOptions } = options ?? {};

  const mutation = useMutation<TData, ApiError, TVariables>({
    mutationKey,
    mutationFn: async (payload: TVariables) => {
      setStageEvent(null);
      try {
        return await streamFn(payload, { onStage: setStageEvent });
      } catch (err) {
        if (err instanceof AnalysisStreamUnavailableError) {
          return fallbackFn(payload);
        }
        throw err;
      }
    },
    onSettled: (...args) => {
      setStageEvent(null);
      onSettled?.(...args);
    },
    ...restOptions,
  });

  return {
    ...mutation,
    currentStage: stageEvent?.stage ?? null,
    stageMessage: stageEvent?.message ?? null,
  };
}

/**
 * Hook to request an explanation for a repository target (file, symbol, or range).
 */
export function useExplainCode(
  repositoryId: string,
  options?: UseMutationOptions<CodeExplanationResponse, ApiError, ExplainCodeRequest>,
) {
  return useStreamingAnalysisMutation(
    ['explain-code', repositoryId],
    (payload, handlers) => streamExplainCode(repositoryId, payload, handlers),
    (payload) => explainCode(repositoryId, payload),
    options,
  );
}

/**
 * Hook to discover related files from the persistent repository intelligence knowledge graph (task.md §6.1).
 */
export function useRelatedFiles(
  repositoryId: string,
  filePath: string | undefined,
  symbol?: string | null,
) {
  return useQuery<RelatedFilesDiscoveryResponse, ApiError>({
    queryKey: ['related-files', repositoryId, filePath, symbol],
    queryFn: () => getRelatedFiles(repositoryId, filePath!, symbol ?? undefined),
    enabled: Boolean(repositoryId && filePath),
    staleTime: 60_000,
  });
}

/**
 * Hook to detect bugs in a repository target (file, symbol, or range).
 */
export function useDetectBugs(
  repositoryId: string,
  options?: UseMutationOptions<BugDetectionResponse, ApiError, BugDetectionRequest>,
) {
  return useStreamingAnalysisMutation(
    ['detect-bugs', repositoryId],
    (payload, handlers) => streamDetectBugs(repositoryId, payload, handlers),
    (payload) => detectBugs(repositoryId, payload),
    options,
  );
}

/**
 * Hook to generate framework-aware tests for a repository target (file, symbol, or range).
 */
export function useGenerateTests(
  repositoryId: string,
  options?: UseMutationOptions<TestGenerationResponse, ApiError, TestGenerationRequest>,
) {
  return useStreamingAnalysisMutation(
    ['generate-tests', repositoryId],
    (payload, handlers) => streamGenerateTests(repositoryId, payload, handlers),
    (payload) => generateTests(repositoryId, payload),
    options,
  );
}

/**
 * Hook to run a standalone AI and static code review on a file, commit, PR, or diff (Week 2 — Day 5).
 */
export function useReviewCode(
  repositoryId: string,
  options?: UseMutationOptions<ReviewReportResponse, ApiError, CodeReviewRequest>,
) {
  return useStreamingAnalysisMutation(
    ['review-code', repositoryId],
    (payload, handlers) => streamReviewCode(repositoryId, payload, handlers),
    (payload) => reviewCode(repositoryId, payload),
    options,
  );
}
