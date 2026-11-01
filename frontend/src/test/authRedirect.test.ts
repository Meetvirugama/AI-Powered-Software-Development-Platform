import { describe, it, expect } from 'vitest';
import { getSafeRedirectPath } from '../lib/authRedirect';

describe('getSafeRedirectPath', () => {
  it('returns /app/dashboard on empty, null, or undefined', () => {
    expect(getSafeRedirectPath(null)).toBe('/app/dashboard');
    expect(getSafeRedirectPath(undefined)).toBe('/app/dashboard');
    expect(getSafeRedirectPath('')).toBe('/app/dashboard');
  });

  it('allows valid internal /app routes', () => {
    expect(getSafeRedirectPath('/app/dashboard')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('/app/repositories')).toBe('/app/repositories');
    expect(getSafeRedirectPath('/app/repositories/123/chat')).toBe('/app/repositories/123/chat');
    expect(getSafeRedirectPath('/app/repositories/abc?tab=review')).toBe('/app/repositories/abc?tab=review');
  });

  it('rejects protocol-relative URLs', () => {
    expect(getSafeRedirectPath('//evil.com')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('//app.com')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('///evil.com')).toBe('/app/dashboard');
  });

  it('rejects paths containing backslashes', () => {
    expect(getSafeRedirectPath('/app\\evil.com')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('\\app\\dashboard')).toBe('/app/dashboard');
  });

  it('rejects paths containing colons or schemes', () => {
    expect(getSafeRedirectPath('/app:alert(1)')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('javascript:alert(1)')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('https://evil.com')).toBe('/app/dashboard');
  });

  it('rejects non-/app paths', () => {
    expect(getSafeRedirectPath('/login')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('/other-route')).toBe('/app/dashboard');
    expect(getSafeRedirectPath('/about')).toBe('/app/dashboard');
  });

  it('rejects directory traversal attempts', () => {
    expect(getSafeRedirectPath('/app/../etc/passwd')).toBe('/app/dashboard');
  });
});

