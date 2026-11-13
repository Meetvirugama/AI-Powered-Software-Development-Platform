/**
 * SSE event type constants and payload shapes (Issue 1 — Real-time events SSE).
 *
 * Supports:
 * - Repository sync updates (`repository.updated`)
 * - Task status & step updates (`task.status.updated`, `task.step.updated`)
 * - Real-time chat token streaming (`chat.stream.started`, `chat.token`, `chat.stream.chunk`, `chat.stream.completed`, `chat.stream.error`)
 * - Granular tool-call progress (`tool.invocation.started`, `tool.invocation.progress`, `tool.invocation.completed`, `tool.invocation.failed`, `tool.approval.requested`, `tool.approval.resolved`)
 * - MCP server notifications & progress (`mcp.notification`, `mcp.progress`, `mcp.elicitation.requested`, `mcp.elicitation.resolved`)
 * - Redis Streams `Last-Event-ID` gap notifications (`sse.stream.gap_detected`)
 */

export const REPO_UPDATED = "repository.updated";
export const TASK_STATUS_UPDATED = "task.status.updated";
export const TASK_STEP_UPDATED = "task.step.updated";

export const CHAT_STREAM_STARTED = "chat.stream.started";
export const CHAT_TOKEN = "chat.token";
export const CHAT_STREAM_CHUNK = "chat.stream.chunk";
export const CHAT_STREAM_COMPLETED = "chat.stream.completed";
export const CHAT_STREAM_ERROR = "chat.stream.error";

export const TOOL_INVOCATION_STARTED = "tool.invocation.started";
export const TOOL_INVOCATION_PROGRESS = "tool.invocation.progress";
export const TOOL_INVOCATION_COMPLETED = "tool.invocation.completed";
export const TOOL_INVOCATION_FAILED = "tool.invocation.failed";
export const TOOL_APPROVAL_REQUESTED = "tool.approval.requested";
export const TOOL_APPROVAL_RESOLVED = "tool.approval.resolved";

export const MCP_NOTIFICATION = "mcp.notification";
export const MCP_PROGRESS = "mcp.progress";
export const MCP_ELICITATION_REQUESTED = "mcp.elicitation.requested";
export const MCP_ELICITATION_RESOLVED = "mcp.elicitation.resolved";

export const SSE_STREAM_CONNECTED = "sse.stream.connected";
export const SSE_GAP_DETECTED = "sse.stream.gap_detected";

export const NAMED_SSE_EVENTS: readonly string[] = [
  REPO_UPDATED,
  TASK_STATUS_UPDATED,
  TASK_STEP_UPDATED,
  CHAT_STREAM_STARTED,
  CHAT_TOKEN,
  CHAT_STREAM_CHUNK,
  CHAT_STREAM_COMPLETED,
  CHAT_STREAM_ERROR,
  TOOL_INVOCATION_STARTED,
  TOOL_INVOCATION_PROGRESS,
  TOOL_INVOCATION_COMPLETED,
  TOOL_INVOCATION_FAILED,
  TOOL_APPROVAL_REQUESTED,
  TOOL_APPROVAL_RESOLVED,
  MCP_NOTIFICATION,
  MCP_PROGRESS,
  MCP_ELICITATION_REQUESTED,
  MCP_ELICITATION_RESOLVED,
  SSE_STREAM_CONNECTED,
  SSE_GAP_DETECTED,
];

/** Raw JSON envelope sent over SSE. */
export interface SseEnvelope {
  id?: string;
  type: string;
  channel?: string;
  timestamp_ms?: number;
  data: unknown;
}

/** Payload for repository.updated events. */
export interface RepoUpdatedPayload {
  repository_id: string;
}

/** Payload for chat.token and chat.stream.completed events. */
export interface ChatTokenPayload {
  session_id: string;
  message_id: string;
  token: string;
  index: number;
  done: boolean;
}

/** Payload for tool.invocation.* progress events. */
export interface ToolProgressPayload {
  task_id: string;
  call_id: string;
  tool_name: string;
  stage: "started" | "progress" | "completed" | "failed" | string;
  progress_pct?: number | null;
  message?: string | null;
  metadata?: Record<string, unknown>;
}

/** Payload for mcp.notification / mcp.progress / mcp.elicitation.* events. */
export interface McpNotificationPayload {
  server_name: string;
  method: string;
  params: Record<string, unknown>;
}

/** Payload for sse.stream.gap_detected events when Last-Event-ID is older than ring/stream retention. */
export interface SseGapDetectedPayload {
  requested_cursor: string;
  oldest_available_cursor: string;
}

/**
 * Map of event type -> handler function.
 * Pass this into RealtimeClient.connect() to register listeners.
 */
export type SseHandlers = Partial<{
  [REPO_UPDATED]: (payload: RepoUpdatedPayload) => void;
  [TASK_STATUS_UPDATED]: (payload: Record<string, unknown>) => void;
  [TASK_STEP_UPDATED]: (payload: Record<string, unknown>) => void;
  [CHAT_STREAM_STARTED]: (payload: Record<string, unknown>) => void;
  [CHAT_TOKEN]: (payload: ChatTokenPayload) => void;
  [CHAT_STREAM_CHUNK]: (payload: ChatTokenPayload) => void;
  [CHAT_STREAM_COMPLETED]: (payload: ChatTokenPayload) => void;
  [CHAT_STREAM_ERROR]: (payload: Record<string, unknown>) => void;
  [TOOL_INVOCATION_STARTED]: (payload: ToolProgressPayload) => void;
  [TOOL_INVOCATION_PROGRESS]: (payload: ToolProgressPayload) => void;
  [TOOL_INVOCATION_COMPLETED]: (payload: ToolProgressPayload) => void;
  [TOOL_INVOCATION_FAILED]: (payload: ToolProgressPayload) => void;
  [TOOL_APPROVAL_REQUESTED]: (payload: Record<string, unknown>) => void;
  [TOOL_APPROVAL_RESOLVED]: (payload: Record<string, unknown>) => void;
  [MCP_NOTIFICATION]: (payload: McpNotificationPayload) => void;
  [MCP_PROGRESS]: (payload: McpNotificationPayload) => void;
  [MCP_ELICITATION_REQUESTED]: (payload: McpNotificationPayload) => void;
  [MCP_ELICITATION_RESOLVED]: (payload: McpNotificationPayload) => void;
  [SSE_GAP_DETECTED]: (payload: SseGapDetectedPayload) => void;
}>;
