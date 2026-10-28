import { useState, useCallback, useMemo } from 'react';
import type {
  AnalysisFeatureType,
  AnalysisTarget,
  AnalysisStatus,
  CodeExplanation,
  BugDetectionResponse,
  TestGenerationResponse,
  ReviewReportResponse,
  ReviewTarget,
} from '../types/analysis';

export interface SingleFeatureState<T, TTarget = AnalysisTarget> {
  status: AnalysisStatus;
  error: string | null;
  errorCode: string | null;
  result: T | null;
  target: TTarget | null;
  runId: string | null;
}

export interface AnalysisStateCollection {
  explain: SingleFeatureState<CodeExplanation, AnalysisTarget>;
  bugs: SingleFeatureState<BugDetectionResponse, AnalysisTarget>;
  tests: SingleFeatureState<TestGenerationResponse, AnalysisTarget>;
  review: SingleFeatureState<ReviewReportResponse, ReviewTarget>;
}

const INITIAL_FEATURE_STATE = {
  status: 'IDLE' as AnalysisStatus,
  error: null,
  errorCode: null,
  result: null,
  target: null,
  runId: null,
};

export const INITIAL_ANALYSIS_STATE: AnalysisStateCollection = {
  explain: { ...INITIAL_FEATURE_STATE },
  bugs: { ...INITIAL_FEATURE_STATE },
  tests: { ...INITIAL_FEATURE_STATE },
  review: { ...INITIAL_FEATURE_STATE },
};

/**
 * Hook providing isolated per-feature lifecycle states, stale response protection,
 * and clean feature switching (F-05).
 */
export function useAnalysisState(initialActiveFeature: AnalysisFeatureType | null = null) {
  const [activeFeature, setActiveFeature] = useState<AnalysisFeatureType | null>(initialActiveFeature);
  const [states, setStates] = useState<AnalysisStateCollection>(INITIAL_ANALYSIS_STATE);

  const startAnalysis = useCallback(
    (feature: AnalysisFeatureType, target: AnalysisTarget | ReviewTarget) => {
      setStates((prev) => ({
        ...prev,
        [feature]: {
          status: 'RUNNING',
          error: null,
          errorCode: null,
          result: null,
          target,
          runId: null,
        },
      }));
    },
    []
  );

  const completeAnalysis = useCallback(
    (
      feature: AnalysisFeatureType,
      result: any,
      target: AnalysisTarget | ReviewTarget,
      runId?: string
    ) => {
      setStates((prev) => {
        const currentTarget = prev[feature].target;
        // Stale response guard (F-05): if target changed before completion, discard or keep strictly bound
        const currentPath = (currentTarget as any)?.path;
        const resultPath = (target as any)?.path;
        if (currentPath && resultPath && currentPath !== resultPath) {
          // Stale response: ignore so it doesn't overwrite new file selection
          return prev;
        }

        return {
          ...prev,
          [feature]: {
            status: 'COMPLETED',
            error: null,
            errorCode: null,
            result,
            target,
            runId: runId ?? (result as any)?.run_id ?? null,
          },
        };
      });
    },
    []
  );

  const failAnalysis = useCallback(
    (
      feature: AnalysisFeatureType,
      errorInput: string | { message: string; code?: string },
      target?: AnalysisTarget | ReviewTarget
    ) => {
      const errorMessage = typeof errorInput === 'string' ? errorInput : errorInput.message;
      const errorCode = typeof errorInput === 'string' ? null : (errorInput.code ?? null);

      setStates((prev) => {
        const currentTarget = prev[feature].target;
        const currentPath = (currentTarget as any)?.path;
        const errorPath = (target as any)?.path;
        if (currentPath && errorPath && currentPath !== errorPath) {
          // Stale error for old file: ignore
          return prev;
        }

        return {
          ...prev,
          [feature]: {
            ...prev[feature],
            status: 'FAILED',
            error: errorMessage,
            errorCode,
          },
        };
      });
    },
    []
  );

  const resetFileFeatures = useCallback((newFilePath?: string) => {
    setStates((prev) => ({
      ...prev,
      explain: { ...INITIAL_FEATURE_STATE },
      bugs: { ...INITIAL_FEATURE_STATE },
      tests: { ...INITIAL_FEATURE_STATE },
      // Review can target git commits/PRs/diffs so we only reset if it was specifically targeting an old file
      review:
        prev.review.target?.type === 'file' && prev.review.target.path !== newFilePath
          ? { ...INITIAL_FEATURE_STATE }
          : prev.review,
    }));
  }, []);

  const reopenFeature = useCallback(
    (feature: AnalysisFeatureType, result: any, target: any, runId?: string) => {
      setActiveFeature(feature);
      setStates((prev) => ({
        ...prev,
        [feature]: {
          status: 'COMPLETED',
          error: null,
          errorCode: null,
          result,
          target,
          runId: runId ?? (result as any)?.run_id ?? null,
        },
      }));
    },
    []
  );

  const currentStatus: AnalysisStatus = useMemo(() => {
    if (!activeFeature) return 'IDLE';
    return states[activeFeature].status;
  }, [activeFeature, states]);

  const currentError: string | null = useMemo(() => {
    if (!activeFeature) return null;
    return states[activeFeature].error;
  }, [activeFeature, states]);

  const isAnyAnalysisPending = useMemo(() => {
    return (
      states.explain.status === 'RUNNING' ||
      states.bugs.status === 'RUNNING' ||
      states.tests.status === 'RUNNING' ||
      states.review.status === 'RUNNING' ||
      states.explain.status === 'PENDING' ||
      states.bugs.status === 'PENDING' ||
      states.tests.status === 'PENDING' ||
      states.review.status === 'PENDING'
    );
  }, [states]);

  return {
    activeFeature,
    setActiveFeature,
    states,
    currentStatus,
    currentError,
    isAnyAnalysisPending,
    startAnalysis,
    completeAnalysis,
    failAnalysis,
    resetFileFeatures,
    reopenFeature,
  };
}
