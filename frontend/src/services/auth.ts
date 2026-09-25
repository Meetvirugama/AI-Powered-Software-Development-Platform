/**
 * Auth service — thin wrapper around the authentication API endpoints.
 *
 * Dependency flow:
 *   useAuth()  →  auth.ts  →  api.ts  →  backend
 *
 * Uses the shared Axios instance from api.ts.
 * No JWT handling. No token storage. Authentication relies on the HTTP-only
 * cookie that the backend sets during the OAuth callback.
 */
import { apiClient } from './api';
import type { User } from '../types/api';

/**
 * Fetch the currently authenticated user.
 * Calls GET /api/v1/auth/me.
 * Returns the User if the session cookie is valid.
 * Throws an ApiError (normalised by the Axios interceptor) on 401 or other failures.
 */
export async function getCurrentUser(): Promise<User> {
  const response = await apiClient.get<User>('/auth/me');
  return response.data;
}

/**
 * Terminate the current session.
 * Calls POST /api/v1/auth/logout.
 * The backend revokes the JWT and deletes the auth cookie.
 * The frontend should clear its local auth state after this resolves.
 */
export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout');
}
