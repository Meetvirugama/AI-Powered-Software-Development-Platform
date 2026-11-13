import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  computeVirtualWindow,
  tokenizeCodeLine,
  parseUnifiedDiffWithTokens,
} from '../utils/virtualizationAndSyntax';
import {
  TaskPlanPhasePanel,
  TaskExecutionPhasePanel,
  TaskVerificationPhasePanel,
  TaskPublicationPhasePanel,
} from '../components/taskStudio/TaskPhasePanels';
import { ToolsIntegrationsAdminPage } from '../pages/ToolsIntegrationsAdminPage';

describe('Issue 2 Frontend Shell: Virtualization, Syntax Highlighting, TaskPhasePanels & Tools Admin UI', () => {
  it('computes bounded virtual windows and tokenizes long/normal code lines safely', () => {
    const win = computeVirtualWindow({
      totalCount: 1000,
      itemHeightPx: 20,
      viewportHeightPx: 200,
      scrollTopPx: 400,
      overscan: 5,
    });
    expect(win.startIndex).toBe(15);
    expect(win.endIndex).toBe(35);
    expect(win.topPaddingPx).toBe(300);
    expect(win.totalHeightPx).toBe(20000);

    const tokens = tokenizeCodeLine('export async function fetchEvents(count = 10) // comment');
    expect(tokens.some((t) => t.kind === 'keyword' && t.text === 'async')).toBe(true);
    expect(tokens.some((t) => t.kind === 'number' && t.text === '10')).toBe(true);
    expect(tokens.some((t) => t.kind === 'comment')).toBe(true);

    const diffLines = parseUnifiedDiffWithTokens(
      '--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n-def old():\n+def new():\n     return True'
    );
    expect(diffLines.length).toBe(4);
    expect(diffLines[1].type).toBe('del');
    expect(diffLines[2].type).toBe('add');
  });

  it('renders decomposed TaskPhasePanels and handles user approvals', () => {
    const onApprovePlan = vi.fn();
    const onResolveApproval = vi.fn();
    const onPublishPR = vi.fn();

    render(
      <div>
        <TaskPlanPhasePanel
          taskId="t-1"
          candidates={[{ filePath: 'backend/app/api/v1/events.py', symbolName: 'stream_events', score: 0.94, rationale: 'SSE endpoint' }]}
          steps={[{ id: 's1', title: 'Add Redis Streams cursor replay', status: 'completed', targetFiles: ['backend/app/api/v1/events.py'] }]}
          isApproved={false}
          onApprovePlan={onApprovePlan}
        />
        <TaskExecutionPhasePanel
          activeTools={[{ callId: 'c1', toolName: 'repo_read_file', stage: 'progress', progressPct: 65, message: 'Reading file' }]}
          pendingApprovals={[{ approvalId: 'ap-1', toolName: 'sandbox_execute_patch', riskTier: 'high', argumentsJson: '{"path":"events.py"}' }]}
          streamingAssistantText="Streaming token delta..."
          onResolveApproval={onResolveApproval}
        />
        <TaskVerificationPhasePanel
          unifiedDiff="@@ -1,1 +1,1 @@
-old
+new"
          repairAttempt={1}
          maxRepairAttempts={3}
          testsPassed={12}
          testsFailed={0}
        />
        <TaskPublicationPhasePanel
          branchName="agent/task-1"
          commitSha="f8f5ade"
          pullRequestUrl={null}
          secretsRedactedCount={2}
          onPublishPullRequest={onPublishPR}
        />
      </div>
    );

    fireEvent.click(screen.getByRole('button', { name: /Approve Plan/i }));
    expect(onApprovePlan).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole('button', { name: /^Approve$/i }));
    expect(onResolveApproval).toHaveBeenCalledWith('ap-1', true);

    fireEvent.click(screen.getByRole('button', { name: /Publish Pull Request/i }));
    expect(onPublishPR).toHaveBeenCalledOnce();
  });

  it('renders ToolsIntegrationsAdminPage, inspects schemas, toggles policies, and registers MCP servers', () => {
    render(<ToolsIntegrationsAdminPage />);

    expect(screen.getByRole('heading', { name: /Tools & MCP Integrations/i })).toBeInTheDocument();
    expect(screen.getByText('Platform Repository Intelligence MCP')).toBeInTheDocument();

    const inspectButtons = screen.getAllByRole('button', { name: /Inspect Schema/i });
    fireEvent.click(inspectButtons[0]);
    expect(screen.getByText(/additionalProperties/i)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Server display name'), {
      target: { value: 'Custom Inspector MCP' },
    });
    fireEvent.change(screen.getByPlaceholderText('Command or endpoint URL'), {
      target: { value: 'npx @modelcontextprotocol/inspector' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Register MCP Server/i }));

    expect(screen.getByText('Custom Inspector MCP')).toBeInTheDocument();
  });
});
