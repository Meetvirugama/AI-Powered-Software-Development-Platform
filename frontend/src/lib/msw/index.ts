/**
 * Lightweight, zero-dependency MSW v2 compatible implementation (msw).
 *
 * Provides http, HttpResponse, delay, bypass, and path-pattern matching
 * compatible with MSW v2 handlers and Axios / Fetch interceptors in Vitest & Browser.
 */

export type PathParams = Record<string, string>;

export interface ResolverInfo {
  request: Request;
  params: PathParams;
  cookies: Record<string, string>;
}

export type ResponseResolver = (
  info: ResolverInfo
) => Response | Promise<Response | undefined> | undefined;

export interface RequestHandler {
  method: string;
  pathPattern: string | RegExp;
  resolver: ResponseResolver;
}

function escapeRegex(str: string): string {
  return str.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Match a request URL against an MSW path pattern or RegExp.
 */
export function matchRequestUrl(
  urlStr: string,
  pattern: string | RegExp
): { matches: boolean; params: PathParams } {
  let pathname = urlStr;
  try {
    const parsed = new URL(urlStr, 'http://localhost');
    pathname = parsed.pathname;
  } catch {
    pathname = urlStr.split('?')[0] || urlStr;
  }

  if (pattern instanceof RegExp) {
    const m = pattern.exec(pathname) || pattern.exec(urlStr);
    if (!m) return { matches: false, params: {} };
    return { matches: true, params: (m.groups as PathParams) || {} };
  }

  let raw = pattern.trim();
  // Strip leading wildcard host prefix
  if (raw.startsWith('*/')) {
    raw = raw.slice(1);
  } else if (/^https?:\/\/[^/]+/.test(raw)) {
    try {
      raw = new URL(raw).pathname;
    } catch {
      // keep raw
    }
  }

  const paramNames: string[] = [];
  const segments = raw.split('/');
  const regexParts = segments.map((seg) => {
    if (seg === '*') {
      return '.*';
    }
    if (seg.startsWith(':')) {
      const paramName = seg.slice(1).replace(/\?$/, '');
      paramNames.push(paramName);
      return '([^/]+)';
    }
    return escapeRegex(seg);
  });

  const regexSource = '^' + regexParts.join('/') + '/?$';
  const regex = new RegExp(regexSource, 'i');
  const match = regex.exec(pathname);
  if (!match) {
    return { matches: false, params: {} };
  }

  const params: PathParams = {};
  paramNames.forEach((name, idx) => {
    params[name] = decodeURIComponent(match[idx + 1] || '');
  });
  return { matches: true, params };
}

function createMethodHelper(method: string) {
  return (pathPattern: string | RegExp, resolver: ResponseResolver): RequestHandler => ({
    method: method.toUpperCase(),
    pathPattern,
    resolver,
  });
}

export const http = {
  get: createMethodHelper('GET'),
  post: createMethodHelper('POST'),
  put: createMethodHelper('PUT'),
  patch: createMethodHelper('PATCH'),
  delete: createMethodHelper('DELETE'),
  options: createMethodHelper('OPTIONS'),
  head: createMethodHelper('HEAD'),
  all: createMethodHelper('ALL'),
};

export class HttpResponse extends Response {
  static json(
    body?: unknown,
    init?: ResponseInit
  ): HttpResponse {
    const headers = new Headers(init?.headers);
    if (!headers.has('content-type')) {
      headers.set('content-type', 'application/json');
    }
    const payload = body === undefined ? 'null' : JSON.stringify(body);
    return new HttpResponse(payload, {
      ...init,
      status: init?.status ?? 200,
      headers,
    });
  }

  static text(
    body?: string,
    init?: ResponseInit
  ): HttpResponse {
    const headers = new Headers(init?.headers);
    if (!headers.has('content-type')) {
      headers.set('content-type', 'text/plain;charset=UTF-8');
    }
    return new HttpResponse(body ?? '', {
      ...init,
      status: init?.status ?? 200,
      headers,
    });
  }

  static error(): Response {
    return Response.error();
  }

  static passthrough(): undefined {
    return undefined;
  }
}

export function passthrough(): undefined {
  return undefined;
}

export async function delay(durationMs: number | 'real' | 'infinite' = 0): Promise<void> {
  if (durationMs === 'infinite') {
    await new Promise(() => {});
    return;
  }
  const ms = durationMs === 'real' ? 10 : durationMs;
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export function bypass(input: RequestInfo | URL, init?: RequestInit): Request {
  const req = new Request(input, init);
  req.headers.set('x-msw-bypass', 'true');
  return req;
}
