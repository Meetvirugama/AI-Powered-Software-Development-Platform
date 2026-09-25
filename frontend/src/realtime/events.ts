/**
 * SSE event type constants and payload shapes.
 *
 * Event names are isolated here so that when the backend SSE contract is
 * finalised, only this file needs updating — not every handler.
 *
 * Current assumption: the backend sends JSON messages of the shape:
 *   { "type": "<event_type>", "data": { ... } }
 *
 * Event names below are the assumed values for `type`. Confirm with the
 * backend lead (Yug) before wiring to production SSE.
 */

// ---------------------------------------------------------------------------
// Event type constants
// ---------------------------------------------------------------------------

/** A repository's sync status or metadata has changed. */
export const REPO_UPDATED = 'repository.updated';

// Future event types (not implemented yet):
// export const TASK_UPDATED    = 'task.updated';
// export const AGENT_EVENT     = 'agent.event';
// export const VERIFY_RESULT   = 'verification.result';
// export const PR_UPDATED      = 'pr.updated';

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

/** Raw JSON envelope sent over SSE. */
export interface SseEnvelope {
  type: string;
  data: unknown;
}

/** Payload for repository.updated events. */
export interface RepoUpdatedPayload {
  /** ID of the repository that changed. */
  repository_id: string;
}

// ---------------------------------------------------------------------------
// Handler map
// ---------------------------------------------------------------------------

/**
 * Map of event type → handler function.
 * Pass this into RealtimeClient.connect() to register listeners.
 */
export type SseHandlers = Partial<{
  [REPO_UPDATED]: (payload: RepoUpdatedPayload) => void;
  // Add future event types here as they are specified.
}>;
