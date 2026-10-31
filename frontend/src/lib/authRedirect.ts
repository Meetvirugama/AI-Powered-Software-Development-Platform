/**
 * Validate and sanitize authentication redirect paths.
 * Only allows relative paths that start with `/app` and do not contain protocol-relative syntax (//),
 * backslashes, colon schemes, or directory traversal.
 */
export function getSafeRedirectPath(rawPath: string | null | undefined, fallback = '/app/dashboard'): string {
  if (!rawPath || typeof rawPath !== 'string') {
    return fallback;
  }

  const trimmed = rawPath.trim();

  // Must begin with /
  if (!trimmed.startsWith('/')) {
    return fallback;
  }

  // Reject protocol-relative URLs (e.g., //evil.com)
  if (trimmed.startsWith('//')) {
    return fallback;
  }

  // Reject backslashes
  if (trimmed.includes('\\')) {
    return fallback;
  }

  // Reject any URL schemes (e.g. javascript:, http:, data:)
  if (trimmed.includes(':')) {
    return fallback;
  }

  // Reject directory traversal segments
  if (trimmed.includes('/..') || trimmed.includes('../')) {
    return fallback;
  }

  // Must be strictly within the application route space (/app)
  if (!trimmed.startsWith('/app')) {
    return fallback;
  }

  return trimmed;
}

