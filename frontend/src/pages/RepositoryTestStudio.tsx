import { useState, useMemo, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  FlaskConical,
  History,
  FolderOpen,
  RefreshCw,
  Terminal,
} from 'lucide-react';
import { useRepositoryFiles } from '../hooks/useRepositories';
import { useGenerateTests } from '../hooks/useAnalysis';
import { useStudioFile } from '../hooks/useStudioFile';
import { CodeViewer } from '../components/explorer/CodeViewer';
import { TestGenerationView } from '../components/explorer/TestGenerationView';
import { AnalysisHistoryDrawer } from '../components/explorer/AnalysisHistoryDrawer';
import { TargetFilePicker } from '../components/studios/TargetFilePicker';
import { ErrorMessage } from '../components/shared/ErrorMessage';
import { checkProposedTestPath } from '../lib/testPath';
import { cn } from '../lib/utils';
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
    <div className="flex flex-col h-full w-full overflow-hidden bg-background">
      {/* Studio Header Toolbar */}
      <div className="flex-shrink-0 bg-card border-b border-border px-4 py-2.5 flex items-center justify-between gap-3 min-w-0">
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Anchored Target File Picker (F-09) */}
          <div className="relative">
            <button
              onClick={() => setShowFilePicker(!showFilePicker)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-foreground transition-colors shadow-xs"
              title="Switch target file"
              aria-expanded={showFilePicker}
              aria-haspopup="dialog"
            >
              <FolderOpen className="h-3.5 w-3.5 text-primary" />
              <span className="truncate max-w-[140px] sm:max-w-[200px]">{selectedFile?.path ?? 'Select File'}</span>
            </button>

            {showFilePicker && (
              <>
                <div
                  className="fixed inset-0 z-20"
                  onClick={() => setShowFilePicker(false)}
                  aria-hidden="true"
                />
                <div className="absolute left-0 top-full mt-1.5 z-30 w-80 sm:w-96 shadow-xl animate-in fade-in-50 zoom-in-95">
                  <TargetFilePicker
                    files={files}
                    isLoading={filesLoading}
                    selectedFile={selectedFile}
                    onSelectFile={handleSelectFile}
                  />
                </div>
              </>
            )}
          </div>

          {testResult?.result?.framework && (
            <div className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 text-[11px] font-mono">
              <Terminal className="h-3 w-3" />
              <span>{testResult.result.framework}</span>
            </div>
          )}

          {/* Responsive Mobile / Tablet Tab Switcher (F-09) */}
          <div className="flex lg:hidden items-center p-0.5 rounded-lg bg-muted text-xs font-medium">
            <button
              onClick={() => setActiveMobileTab('source')}
              className={cn(
                'px-2.5 py-1 rounded-md transition-colors',
                activeMobileTab === 'source'
                  ? 'bg-background text-foreground shadow-2xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Source
            </button>
            <button
              onClick={() => setActiveMobileTab('results')}
              className={cn(
                'px-2.5 py-1 rounded-md transition-colors',
                activeMobileTab === 'results'
                  ? 'bg-background text-foreground shadow-2xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Results
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setHistoryOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-background hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title="View test generation history"
            aria-label="View test generation history"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">History</span>
          </button>

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
        </div>
      </div>

      {/* Responsive Split Studio Canvas (F-09) */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left Pane: Code Viewer */}
        <div
          className={cn(
            'w-full lg:w-1/2 min-w-0 h-full lg:border-r border-border flex flex-col min-h-0 overflow-hidden bg-background',
            activeMobileTab !== 'source' && 'hidden lg:flex'
          )}
        >
          {selectedFile ? (
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
          )}
        </div>

        {/* Right Pane: Generated Test Suite Canvas */}
        <div
          className={cn(
            'flex-1 lg:w-1/2 min-w-0 h-full flex flex-col min-h-0 overflow-y-auto bg-card/30 p-4 lg:p-6',
            activeMobileTab !== 'results' && 'hidden lg:flex'
          )}
        >
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
              <ErrorMessage
                error={testMutation.error}
              />
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
      </div>

      {/* History Drawer */}
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
    </div>
  );
}

export default RepositoryTestStudio;
