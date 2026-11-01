import { describe, it, expect } from 'vitest';
import { classifyAnalysisError } from '../lib/classifyAnalysisError';

describe('classifyAnalysisError (F-11)', () => {
  it('classifies UNSUPPORTED_TARGET, UNSUPPORTED_LANGUAGE, and INVALID_FRAMEWORK into distinct unsupported state', () => {
    const r1 = classifyAnalysisError('UNSUPPORTED_TARGET');
    expect(r1.category).toBe('UNSUPPORTED_TARGET');
    expect(r1.isUnsupportedTarget).toBe(true);
    expect(r1.title).toBe('Target Not Supported for Unit Tests');

    const r2 = classifyAnalysisError('UNSUPPORTED_LANGUAGE');
    expect(r2.category).toBe('UNSUPPORTED_TARGET');
    expect(r2.isUnsupportedTarget).toBe(true);

    const r3 = classifyAnalysisError('INVALID_FRAMEWORK');
    expect(r3.category).toBe('UNSUPPORTED_TARGET');
    expect(r3.isUnsupportedTarget).toBe(true);

    // Static non-code file for test generation
    const r4 = classifyAnalysisError(null, null, 'tests', true);
    expect(r4.category).toBe('UNSUPPORTED_TARGET');
    expect(r4.isUnsupportedTarget).toBe(true);
  });

  it('classifies NOT_FOUND and FILE_NOT_FOUND into distinct not-found state', () => {
    const r1 = classifyAnalysisError('NOT_FOUND');
    expect(r1.category).toBe('NOT_FOUND');
    expect(r1.isNotFound).toBe(true);
    expect(r1.title).toBe('Target File Not Found');

    const r2 = classifyAnalysisError('FILE_NOT_FOUND');
    expect(r2.category).toBe('NOT_FOUND');
    expect(r2.isNotFound).toBe(true);
  });

  it('classifies REQUEST_TIMEOUT and TIMEOUT with clear history check guidance (F-04)', () => {
    const r1 = classifyAnalysisError('REQUEST_TIMEOUT');
    expect(r1.category).toBe('TIMEOUT');
    expect(r1.isTimeout).toBe(true);
    expect(r1.title).toBe('Analysis Request Timed Out');
    expect(r1.userGuidance).toContain('check Analysis History before retrying');

    const r2 = classifyAnalysisError('TIMEOUT');
    expect(r2.category).toBe('TIMEOUT');
    expect(r2.isTimeout).toBe(true);
  });

  it('classifies SERVICE_UNAVAILABLE and PROVIDER_UNAVAILABLE into provider unavailable state', () => {
    const r1 = classifyAnalysisError('SERVICE_UNAVAILABLE');
    expect(r1.category).toBe('PROVIDER_UNAVAILABLE');
    expect(r1.isProviderUnavailable).toBe(true);
    expect(r1.title).toBe('AI Service Temporarily Unavailable');

    const r2 = classifyAnalysisError('PROVIDER_UNAVAILABLE');
    expect(r2.category).toBe('PROVIDER_UNAVAILABLE');
    expect(r2.isProviderUnavailable).toBe(true);
  });

  it('classifies RATE_LIMITED and VALIDATION_ERROR into distinct states', () => {
    const r1 = classifyAnalysisError('RATE_LIMITED');
    expect(r1.category).toBe('RATE_LIMITED');
    expect(r1.title).toBe('Rate Limit Reached');

    const r2 = classifyAnalysisError('INVALID_REQUEST');
    expect(r2.category).toBe('VALIDATION_ERROR');
    expect(r2.title).toBe('Invalid Request Parameters');
  });

  it('routes unknown or generic server errors to generic server error state', () => {
    const r1 = classifyAnalysisError('SERVER_ERROR');
    expect(r1.category).toBe('GENERIC_SERVER_ERROR');
    expect(r1.title).toBe('Analysis Failed');

    const r2 = classifyAnalysisError(null, 'Some random error string');
    expect(r2.category).toBe('GENERIC_SERVER_ERROR');
    expect(r2.title).toBe('Analysis Failed');
  });
});
