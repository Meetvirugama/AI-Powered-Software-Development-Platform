/**
 * Pure classification function for analysis errors (F-11).
 *
 * Replaces fragile error-message substring matching with structured error code
 * checks and feature-specific validation logic.
 */

export type ClassifiedErrorCategory =
  | 'UNSUPPORTED_TARGET'
  | 'NOT_FOUND'
  | 'TIMEOUT'
  | 'PROVIDER_UNAVAILABLE'
  | 'RATE_LIMITED'
  | 'VALIDATION_ERROR'
  | 'GENERIC_SERVER_ERROR';

export interface ClassifiedAnalysisError {
  category: ClassifiedErrorCategory;
  title: string;
  isUnsupportedTarget: boolean;
  isTimeout: boolean;
  isProviderUnavailable: boolean;
  isNotFound: boolean;
  userGuidance: string;
}

export function classifyAnalysisError(
  errorCode?: string | null,
  _errorMessage?: string | null,
  feature?: string | null,
  isStaticNonCode?: boolean
): ClassifiedAnalysisError {
  const code = (errorCode || '').toUpperCase();

  // 1. Unsupported target / language / framework
  if (
    code === 'UNSUPPORTED_TARGET' ||
    code === 'UNSUPPORTED_LANGUAGE' ||
    code === 'INVALID_FRAMEWORK' ||
    (feature === 'tests' && isStaticNonCode)
  ) {
    return {
      category: 'UNSUPPORTED_TARGET',
      title: 'Target Not Supported for Unit Tests',
      isUnsupportedTarget: true,
      isTimeout: false,
      isProviderUnavailable: false,
      isNotFound: false,
      userGuidance:
        'Unit test generation requires supported executable code (Python, TypeScript, JavaScript). Static assets and configuration files cannot be targeted.',
    };
  }

  // 2. Resource / File Not Found
  if (
    code === 'NOT_FOUND' ||
    code === 'FILE_NOT_FOUND' ||
    code === 'RESOURCE_NOT_FOUND' ||
    code === 'REPOSITORY_NOT_FOUND'
  ) {
    return {
      category: 'NOT_FOUND',
      title: 'Target File Not Found',
      isUnsupportedTarget: false,
      isTimeout: false,
      isProviderUnavailable: false,
      isNotFound: true,
      userGuidance:
        'The requested file or resource could not be found. Please ensure the repository is fully indexed.',
    };
  }

  // 3. Timeout (F-04)
  if (code === 'REQUEST_TIMEOUT' || code === 'TIMEOUT') {
    return {
      category: 'TIMEOUT',
      title: 'Analysis Request Timed Out',
      isUnsupportedTarget: false,
      isTimeout: true,
      isProviderUnavailable: false,
      isNotFound: false,
      userGuidance:
        'The analysis took longer than expected. The backend may still be processing — please check Analysis History before retrying.',
    };
  }

  // 4. Provider / Service Unavailable
  if (
    code === 'SERVICE_UNAVAILABLE' ||
    code === 'PROVIDER_UNAVAILABLE' ||
    code === 'PROVIDER_ERROR'
  ) {
    return {
      category: 'PROVIDER_UNAVAILABLE',
      title: 'AI Service Temporarily Unavailable',
      isUnsupportedTarget: false,
      isTimeout: false,
      isProviderUnavailable: true,
      isNotFound: false,
      userGuidance:
        'The AI model provider is experiencing temporary unavailability. Please wait a moment and retry.',
    };
  }

  // 5. Rate Limited
  if (code === 'RATE_LIMITED') {
    return {
      category: 'RATE_LIMITED',
      title: 'Rate Limit Reached',
      isUnsupportedTarget: false,
      isTimeout: false,
      isProviderUnavailable: false,
      isNotFound: false,
      userGuidance:
        'Rate limit has been exceeded. Please wait a brief moment before submitting another request.',
    };
  }

  // 6. Validation Error
  if (code === 'INVALID_REQUEST' || code === 'BAD_REQUEST' || code === 'VALIDATION_ERROR') {
    return {
      category: 'VALIDATION_ERROR',
      title: 'Invalid Request Parameters',
      isUnsupportedTarget: false,
      isTimeout: false,
      isProviderUnavailable: false,
      isNotFound: false,
      userGuidance: 'The request parameters were invalid or could not be processed.',
    };
  }

  // Fallback / Generic Server Error
  return {
    category: 'GENERIC_SERVER_ERROR',
    title: 'Analysis Failed',
    isUnsupportedTarget: false,
    isTimeout: false,
    isProviderUnavailable: false,
    isNotFound: false,
    userGuidance: 'An unexpected error occurred while executing the analysis.',
  };
}
