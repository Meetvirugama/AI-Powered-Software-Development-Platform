import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  FlaskConical,
  RefreshCw,
  Terminal,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useGenerateTests } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { TestGenerationView } from '../components/explorer/TestGenerationView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { StudioLayout } from '../components/studios/StudioLayout';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { checkProposedTestPath } from '../lib/testPath';
import type {
  SourceReference,
  TestGenerationResponse,
  SupportedTestFramework,
} from '../types/analysis';

export function RepositoryTestStudio() {
  const { id } = useParams<{ id: string }>();

  const repoId = id ?? '';
  const { data: filesData, isLoading: filesLoading, isError: filesError } = useRepositoryFiles(repoId, 1, 500);
  const files = useMemo(() => filesData?.items ?? [], [filesData]);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeSourceReference, setActiveSourceReference] = useState<SourceReference | null>(null);
  const [testResult, setTestResult] = useState<TestGenerationResponse | null>(null);
  const [frameworkOverride, setFrameworkOverride] = useState<SupportedTestFramework | null>(null);
  const [activeMobileTab, setActiveMobileTab] = useState<'source' | 'results'>('source');

  const {
    selectedFile,
    activeTarget,
    showFilePicker,
    setShowFilePicker,
    handleSelectFile,
    handleTargetChange,
  } = useStudioFile(files, () => {
    setActiveSourceReference(null);
    setTestResult(null);
  });

  // Test generation mutation
  const testMutation = useGenerateTests(repoId, {
    onSuccess: (data) => {
      setTestResult(data);
      setActiveMobileTab('results');
    },
  });

  const handleRunGenerate = useCallback(() => {
    if (!selectedFile || testMutation.isPending) return;

    testMutation.mutate({
      target: activeTarget,
      framework: frameworkOverride ?? undefined,
    });
  }, [selectedFile, activeTarget, frameworkOverride, testMutation]);

  // Compute proposed test path status
  const proposedPathStatus = useMemo(() => {
    if (!testResult?.result?.proposed_test_path) return 'UNKNOWN';
    return checkProposedTestPath(
      testResult.result.proposed_test_path,
      files,
      filesLoading,
      filesError,
      false
    );
  }, [testResult, files, filesLoading, filesError]);

  return (
    <StudioLayout
      files={files}
      filesLoading={filesLoading}
      selectedFile={selectedFile}
      onSelectFile={handleSelectFile}
      showFilePicker={showFilePicker}
      onToggleFilePicker={setShowFilePicker}
      activeTarget={activeTarget}
      activeMobileTab={activeMobileTab}
      onMobileTabChange={setActiveMobileTab}
      onOpenHistory={() => setHistoryOpen(true)}
      historyTitle="View test generation history"
      extraControls={
        testResult?.result?.framework ? (
          <div className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 text-[11px] font-mono">
            <Terminal className="h-3 w-3" />
            <span>{testResult.result.framework}</span>
          </div>
        ) : undefined
      }
      actionButton={
        <button
          onClick={handleRunGenerate}
          disabled={!selectedFile || testMutation.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors shadow-xs disabled:opacity-50"
        >
          {testMutation.isPending ? (
            <>
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              <span>Generating...</span>
            </>
          ) : (
            <>
              <FlaskConical className="h-3.5 w-3.5" />
              <span>Generate Tests</span>
            </>
          )}
        </button>
      }
      sourcePanel={
        selectedFile ? (
          <CodeViewer
            repositoryId={repoId}
            file={selectedFile}
            activeTarget={activeTarget}
            onTargetChange={handleTargetChange}
            highlightedSource={activeSourceReference}
            onClearHighlightedSource={() => setActiveSourceReference(null)}
            onTriggerExplain={handleRunGenerate}
            isAnalyzing={testMutation.isPending}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center p-8 text-center text-muted-foreground text-xs">
            Select a file to inspect its source code.
          </div>
        )
      }
      resultsPanel={
        <div className="flex-1 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6">
          {testMutation.isPending ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
              <div className="h-12 w-12 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary animate-pulse">
                <FlaskConical className="h-6 w-6 animate-spin" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">Generating framework-aware test suite...</h3>
              <p className="text-xs text-muted-foreground max-w-sm">
                Synthesizing happy path, boundary condition, and exception test cases with syntax validation.
              </p>
            </div>
          ) : testMutation.isError ? (
            <div className="p-4">
              <ErrorMessage error={testMutation.error} />
            </div>
          ) : testResult?.result ? (
            <div className="space-y-4">
              <TestGenerationView
                result={testResult.result}
                proposedPathStatus={proposedPathStatus}
                proposedPathExists={proposedPathStatus === 'EXISTS'}
                activeSourceReference={activeSourceReference}
                onSelectSourceReference={(ref) => {
                  setActiveSourceReference(ref);
                  setActiveMobileTab('source');
                }}
                onSelectFramework={setFrameworkOverride}
                selectedFrameworkOverride={frameworkOverride}
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center max-w-md mx-auto space-y-4">
              <div className="h-12 w-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-xs">
                <FlaskConical className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-foreground tracking-tight">Test Generation Studio</h3>
                <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                  Generate comprehensive unit and integration test suites adhering to project conventions (pytest, unittest, vitest, or jest) with automated syntax validation.
                </p>
              </div>

              <div className="w-full pt-2">
                <button
                  onClick={handleRunGenerate}
                  disabled={!selectedFile}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded-md bg-primary hover:bg-primary/90 text-primary-foreground transition-colors shadow-xs"
                >
                  <FlaskConical className="h-3.5 w-3.5" />
                  <span>Generate Tests for Current File ({selectedFile?.path.split('/').pop() ?? 'None'})</span>
                </button>
              </div>
            </div>
          )}
        </div>
      }
      historyDrawer={
        <AnalysisHistoryDrawer
          isOpen={historyOpen}
          onClose={() => setHistoryOpen(false)}
          repositoryId={repoId}
          initialFeature="tests"
          currentFilePath={selectedFile?.path}
          onReopenTests={(tests, target) => {
            setTestResult(tests);
            handleTargetChange(target);
            setActiveMobileTab('results');
            setHistoryOpen(false);
          }}
        />
      }
    />
  );
}

export default RepositoryTestStudio;
