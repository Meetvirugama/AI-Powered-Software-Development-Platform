/**
 * MSW v2 Node Server Interceptor (`msw/node`) for Vitest / JSDOM.
 *
 * Intercepts both `globalThis.fetch` and `globalThis.XMLHttpRequest` (used by Axios in JSDOM)
 * and routes matching requests through registered MSW v2 `http.*` handlers.
 */

import { matchRequestUrl, type RequestHandler } from './index';

export interface SetupServerApi {
  listen: (options?: { onUnhandledRequest?: 'bypass' | 'warn' | 'error' | ((req: Request) => void) }) => void;
  resetHandlers: (...nextHandlers: RequestHandler[]) => void;
  use: (...runtimeHandlers: RequestHandler[]) => void;
  close: () => void;
  listHandlers: () => readonly RequestHandler[];
}

export function setupServer(...initialHandlers: RequestHandler[]): SetupServerApi {
  const defaultHandlers: RequestHandler[] = [...initialHandlers];
  let activeHandlers: RequestHandler[] = [...initialHandlers];
  let originalFetch: typeof globalThis.fetch | null = null;
  let OriginalXHR: typeof XMLHttpRequest | null = null;

  async function resolveRequest(req: Request): Promise<Response | null> {
    if (req.headers.get('x-msw-bypass') === 'true') {
      return null;
    }

    const method = req.method.toUpperCase();
    const url = req.url;

    for (const handler of activeHandlers) {
      if (handler.method !== 'ALL' && handler.method !== method) {
        continue;
      }
      const { matches, params } = matchRequestUrl(url, handler.pathPattern);
      if (matches) {
        const cloned = req.clone();
        const response = await handler.resolver({
          request: cloned,
          params,
          cookies: {},
        });
        if (response instanceof Response) {
          return response;
        }
      }
    }
    return null;
  }

  function installFetchInterceptor() {
    if (originalFetch) return;
    originalFetch = globalThis.fetch;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const urlStr =
        typeof input === 'string'
          ? input.startsWith('http')
            ? input
            : `http://localhost${input.startsWith('/') ? '' : '/'}${input}`
          : input instanceof URL
          ? input.toString()
          : input.url;

      const req =
        input instanceof Request
          ? new Request(urlStr, {
              method: init?.method || input.method,
              headers: init?.headers || input.headers,
              body: init?.body !== undefined ? init.body : input.body,
              signal: init?.signal || input.signal,
            })
          : new Request(urlStr, init);

      const mocked = await resolveRequest(req);
      if (mocked) {
        return mocked;
      }
      if (originalFetch) {
        return originalFetch(input, init);
      }
      throw new Error(`Unhandled fetch request: ${req.method} ${req.url}`);
    };
  }

  function installXHRInterceptor() {
    if (typeof globalThis.XMLHttpRequest === 'undefined' || OriginalXHR) return;
    OriginalXHR = globalThis.XMLHttpRequest;

    class MockXMLHttpRequest extends EventTarget {
      static readonly UNSENT = 0;
      static readonly OPENED = 1;
      static readonly HEADERS_RECEIVED = 2;
      static readonly LOADING = 3;
      static readonly DONE = 4;

      readonly UNSENT = 0;
      readonly OPENED = 1;
      readonly HEADERS_RECEIVED = 2;
      readonly LOADING = 3;
      readonly DONE = 4;

      readyState = 0;
      status = 0;
      statusText = '';
      response: any = '';
      responseText = '';
      responseType: XMLHttpRequestResponseType = '';
      responseURL = '';
      timeout = 0;
      withCredentials = false;
      upload = new EventTarget();

      onreadystatechange: ((this: XMLHttpRequest, ev: Event) => any) | null = null;
      onload: ((this: XMLHttpRequest, ev: ProgressEvent) => any) | null = null;
      onloadend: ((this: XMLHttpRequest, ev: ProgressEvent) => any) | null = null;
      onerror: ((this: XMLHttpRequest, ev: ProgressEvent) => any) | null = null;
      ontimeout: ((this: XMLHttpRequest, ev: ProgressEvent) => any) | null = null;
      onabort: ((this: XMLHttpRequest, ev: ProgressEvent) => any) | null = null;

      private _method = 'GET';
      private _url = '';
      private _requestHeaders = new Map<string, string>();
      private _responseHeaders = new Map<string, string>();
      private _aborted = false;

      open(method: string, url: string | URL): void {
        this._method = (method || 'GET').toUpperCase();
        const rawUrl = String(url);
        this._url = rawUrl.startsWith('http')
          ? rawUrl
          : `http://localhost${rawUrl.startsWith('/') ? '' : '/'}${rawUrl}`;
        this.readyState = 1;
        this._fireReadyStateChange();
      }

      setRequestHeader(name: string, value: string): void {
        const key = name.toLowerCase();
        const existing = this._requestHeaders.get(key);
        this._requestHeaders.set(key, existing ? `${existing}, ${value}` : value);
      }

      getResponseHeader(name: string): string | null {
        return this._responseHeaders.get(name.toLowerCase()) ?? null;
      }

      getAllResponseHeaders(): string {
        const lines: string[] = [];
        this._responseHeaders.forEach((val, key) => {
          lines.push(`${key}: ${val}`);
        });
        return lines.join('\r\n');
      }

      overrideMimeType(): void {}

      abort(): void {
        this._aborted = true;
        this.readyState = 0;
        const evt = new ProgressEvent('abort');
        this.dispatchEvent(evt);
        if (this.onabort) this.onabort.call(this as unknown as XMLHttpRequest, evt);
      }

      send(body?: Document | XMLHttpRequestBodyInit | null): void {
        const headers = new Headers();
        this._requestHeaders.forEach((v, k) => headers.set(k, v));

        let reqBody: BodyInit | null | undefined = undefined;
        if (body !== undefined && body !== null && this._method !== 'GET' && this._method !== 'HEAD') {
          reqBody = typeof body === 'string' ? body : (body as BodyInit);
        }

        const req = new Request(this._url, {
          method: this._method,
          headers,
          body: reqBody,
        });

        resolveRequest(req)
          .then(async (res) => {
            if (this._aborted) return;

            if (!res) {
              // Default 404 JSON response if no handler matched
              this.status = 404;
              this.statusText = 'Not Found';
              this._responseHeaders.set('content-type', 'application/json');
              const fallbackText = JSON.stringify({
                error: { code: 'NOT_FOUND', message: `No mock handler for ${this._method} ${this._url}` },
              });
              this._finalizeResponse(fallbackText);
              return;
            }

            this.status = res.status;
            this.statusText = res.statusText || (res.status >= 200 && res.status < 300 ? 'OK' : 'Error');
            this.responseURL = this._url;
            res.headers.forEach((v, k) => {
              this._responseHeaders.set(k.toLowerCase(), v);
            });

            this.readyState = 2;
            this._fireReadyStateChange();
            this.readyState = 3;
            this._fireReadyStateChange();

            const text = await res.text();
            this._finalizeResponse(text);
          })
          .catch(() => {
            if (this._aborted) return;
            this.readyState = 4;
            this.status = 0;
            const errEvt = new ProgressEvent('error');
            this.dispatchEvent(errEvt);
            if (this.onerror) this.onerror.call(this as unknown as XMLHttpRequest, errEvt);
            const endEvt = new ProgressEvent('loadend');
            this.dispatchEvent(endEvt);
            if (this.onloadend) this.onloadend.call(this as unknown as XMLHttpRequest, endEvt);
          });
      }

      private _finalizeResponse(text: string): void {
        this.responseText = text;
        if (this.responseType === 'json') {
          try {
            this.response = text ? JSON.parse(text) : null;
          } catch {
            this.response = null;
          }
        } else {
          this.response = text;
        }
        this.readyState = 4;
        this._fireReadyStateChange();

        const loadEvt = new ProgressEvent('load');
        this.dispatchEvent(loadEvt);
        if (this.onload) this.onload.call(this as unknown as XMLHttpRequest, loadEvt);

        const loadEndEvt = new ProgressEvent('loadend');
        this.dispatchEvent(loadEndEvt);
        if (this.onloadend) this.onloadend.call(this as unknown as XMLHttpRequest, loadEndEvt);
      }

      private _fireReadyStateChange(): void {
        const evt = new Event('readystatechange');
        this.dispatchEvent(evt);
        if (this.onreadystatechange) {
          this.onreadystatechange.call(this as unknown as XMLHttpRequest, evt);
        }
      }
    }

    globalThis.XMLHttpRequest = MockXMLHttpRequest as unknown as typeof XMLHttpRequest;
  }

  return {
    listen() {
      installFetchInterceptor();
      installXHRInterceptor();
    },
    resetHandlers(...nextHandlers: RequestHandler[]) {
      if (nextHandlers.length > 0) {
        activeHandlers = [...nextHandlers];
      } else {
        activeHandlers = [...defaultHandlers];
      }
    },
    use(...runtimeHandlers: RequestHandler[]) {
      // Runtime handlers take precedence (LIFO before defaults)
      activeHandlers = [...runtimeHandlers, ...activeHandlers];
    },
    close() {
      if (originalFetch) {
        globalThis.fetch = originalFetch;
        originalFetch = null;
      }
      if (OriginalXHR) {
        globalThis.XMLHttpRequest = OriginalXHR;
        OriginalXHR = null;
      }
    },
    listHandlers() {
      return activeHandlers;
    },
  };
}
