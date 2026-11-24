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
import { listMCPServers, pingMCPServer } from '../services/mcp';
import type { MCPServerRegistration } from '../services/mcp';

vi.mock('../services/mcp', () => ({
  listMCPServers: vi.fn(),
  pingMCPServer: vi.fn(),
}));

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
          unifiedDiff={"@@ -1,1 +1,1 @@\n-old\n+new"}
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

  it('shows actual MCP tools and displays latency only after a server response', async () => {
    const server: MCPServerRegistration = {
      id: 'mcp-platform-core',
      name: 'Platform Repository Intelligence MCP',
      transport: 'in_process',
      endpointOrCommand: 'Built-in dispatcher',
      enabled: true,
      status: 'connected',
      protocolVersion: '2024-11-05',
      lastLatencyMs: null,
      tools: [{
        name: 'repo_read_file',
        description: 'Read a repository file',
        riskTier: 'low',
        requiresApproval: false,
        inputSchemaJson: '{"additionalProperties":false}',
      }],
    };
    vi.mocked(listMCPServers).mockResolvedValue([server]);
    vi.mocked(pingMCPServer).mockResolvedValue({ ...server, lastLatencyMs: 7 });

    render(<ToolsIntegrationsAdminPage />);
    expect(await screen.findByText(server.name)).toBeInTheDocument();
    expect(screen.queryByText(/7ms/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Inspect Schema' }));
    expect(screen.getByText(/additionalProperties/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ping dispatcher' }));
    expect(await screen.findByText(/7ms/)).toBeInTheDocument();
    expect(pingMCPServer).toHaveBeenCalledWith(server.id);
    expect(screen.queryByRole('button', { name: /Register|Disable Server/ })).not.toBeInTheDocument();
  });

  it('reports MCP API errors without fabricating catalog entries', async () => {
    vi.mocked(listMCPServers).mockRejectedValue(new Error('unavailable'));
    render(<ToolsIntegrationsAdminPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load the MCP tool catalog.');
    expect(screen.queryByText('Platform Repository Intelligence MCP')).not.toBeInTheDocument();
  });
});
