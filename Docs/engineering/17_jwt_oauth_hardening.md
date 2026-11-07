# 17. JWT & GitHub OAuth Security Hardening (Batch 1 — Issue #181)
> **Version:** 1.0 | **Created:** 2026-11-07 | **Status:** Implemented & Verified

---

## Overview

This document specifies the technical architecture and security policies implemented in Batch 1 of Issue #181 (`feat(auth): harden JWT validation and GitHub OAuth security`).
The objective is to eliminate critical cryptographic ambiguities, establish fail-closed state management, enforce strict OAuth 2.0 PKCE, and harden browser-facing cookie and CSRF protections without breaking existing authentication workflows.

---

## 1. Platform JWT Claim Contract

All platform access tokens issued by `app.core.security.create_access_token` strictly conform to the following schema and algorithm policy:

### Permitted Algorithms
Platform access tokens permit **only symmetric HMAC algorithms**:
- Allowlist: `{"HS256", "HS384", "HS512"}` (Default: `HS256`)
- Asymmetric algorithms (`RS256`, `ES256`, `none`, etc.) are explicitly rejected prior to signature verification.

### Mandatory Claims Matrix

| Claim | Type | Description | Validation Rule |
|---|---|---|---|
| `sub` | `str` | Subject (User UUID) | Required, must be a non-empty string |
| `jti` | `str` | JWT ID (Token UUID) | Required, cryptographically unique UUID4 string |
| `iss` | `str` | Issuer | Required, must strictly match configured `settings.jwt_issuer` (default: `"agent-platform"`) |
| `aud` | `str` | Audience | Required, must strictly match configured `settings.jwt_audience` (default: `"agent-platform-web"`) |
| `token_type` | `str` | Token Purpose | Required, must strictly equal `"access"` |
| `type` | `str` | Backward-compatibility mirror | Mirror of `token_type` (`"access"`) |
| `iat` | `int` | Issued-At Timestamp | Required UTC epoch timestamp, must be `<= current_time + skew` |
| `exp` | `int` | Expiration Timestamp | Required UTC epoch timestamp, must be `> iat` and `> current_time` |

### Error Sanitization
Internal JWT decoding exceptions (`ExpiredSignatureError`, `InvalidSignatureError`, `MissingRequiredClaimError`, `InvalidAudienceError`, `InvalidIssuerError`) are caught and masked behind a uniform `401 Unauthorized` API error envelope (`ErrorCode.UNAUTHORIZED`) with generic, safe client-facing messages ("Invalid or expired access token." or "Invalid access token.") to prevent token-probing timing/oracle attacks.

---

## 2. Platform HS256 vs GitHub App RS256 Trust-Domain Separation

The platform enforces total cryptographic isolation between internal user access tokens and GitHub App API authentication:

| Dimension | Platform Access Tokens | GitHub App Installation Tokens |
|---|---|---|
| **Trust Domain** | Internal Platform User Sessions | GitHub REST API Authentication |
| **Algorithm** | Symmetric `HS256` | Asymmetric `RS256` |
| **Key Source** | `settings.jwt_secret` (HMAC Shared Secret) | `settings.github_app_private_key` (RSA PEM Private Key) |
| **Audience** | `settings.jwt_audience` (`"agent-platform-web"`) | GitHub API (`"https://api.github.com"` implicitly / not set) |
| **Issuer** | `settings.jwt_issuer` (`"agent-platform"`) | `settings.github_app_id` (Numeric GitHub App ID) |
| **Lifespan** | Configurable, default 15 minutes | 10 minutes (60-second backward skew for clock drift) |
| **Consolidation** | PyJWT (`import jwt`) | PyJWT (`import jwt`) |

Neither key material nor verification algorithms can be interchanged:
- The platform token decoder rejects tokens signed with RSA keys or any algorithm not in the HMAC allowlist.
- GitHub App tokens cannot be verified or decoded by the platform access token validator.

---

## 3. GitHub OAuth State Lifecycle & PKCE S256

GitHub OAuth login (`/api/v1/auth/github/login`) and callback (`/api/v1/auth/github/callback`) implement hardened CSRF defense and RFC 7636 PKCE (Proof Key for Code Exchange):

```
Browser                       Backend API                          Redis                       GitHub OAuth
   |                               |                                 |                              |
   |--- GET /auth/github/login --->|                                 |                              |
   |                               |-- Gen state (32B urlsafe)       |                              |
   |                               |-- Gen verifier (64B urlsafe)    |                              |
   |                               |-- Compute SHA256 challenge      |                              |
   |                               |-- SETEX oauth:state:{s} 600s -->|                              |
   |                               |<-- (fail-closed if down 503) ---|                              |
   |<-- 307 Redirect to GitHub ----|                                 |                              |
   |    + Set-Cookie: oauth_state  |                                 |                              |
   |                               |                                 |                              |
   |==================== Authenticate on GitHub ===================================================>|
   |                               |                                 |                              |
   |<------------------- 302 Callback with ?code=C&state=S -----------------------------------------|
   |                               |                                 |                              |
   |--- GET /callback?code&state ->|                                 |                              |
   |    + Cookie: oauth_state      |                                 |                              |
   |                               |-- Verify cookie == query state  |                              |
   |                               |-- Atomic GETDEL state payload ->|                              |
   |                               |<-- Returns payload (or None) ---|                              |
   |                               |    (fail-closed if down 503)    |                              |
   |                               |-- POST /login/oauth/access_token (code, verifier) ------------->|
   |                               |<-- Return access_token ----------------------------------------|
   |<-- 307 Redirect to Frontend --|                                 |                              |
   |    + Clear oauth_state cookie |                                 |                              |
   |    + Set auth_token cookie    |                                 |                              |
```

### State Management Details
1. **Cryptographic Entropy**: Generated via `secrets.token_urlsafe(32)`.
2. **PKCE Parameters**:
   - `code_verifier`: 64 bytes generated via `secrets.token_urlsafe(64)`.
   - `code_challenge`: SHA256 hash of `code_verifier`, URL-safe base64-encoded without trailing `=`.
   - `code_challenge_method`: `S256`.
3. **Atomic State Consumption**:
   - States are consumed via Redis `GETDEL` (Redis 6.2+).
   - If `GETDEL` is unsupported by an older Redis server or cluster proxy, fallback executes an atomic Lua script (`redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1])`).
   - Replay attacks and concurrent racing callbacks are rejected immediately.
4. **Cookie Binding & Cleanup**:
   - `oauth_state` cookie is stored with `httponly=True`, `samesite="lax"`, `secure=settings.cookie_secure`, `max_age=600`.
   - The cookie is cleared on **both success and failure**, preventing leftover state tokens in the browser.

---

## 4. Fail-Closed Redis Architecture

The authentication subsystem treats Redis as a critical security dependency. All state and revocation lookups **fail closed**:

### 1. Token Revocation Fail-Closed (`_is_token_blocklisted_async`)
- If Redis is unreachable, times out, throws a `RedisError`, or the Redis client instance is unavailable, token validation does **not** assume the token is valid.
- The request immediately raises `HTTP 503 Service Unavailable` with `ErrorCode.SERVICE_UNAVAILABLE`.
- Valid unrevoked tokens only authenticate when Redis explicitly returns `0` (key does not exist).

### 2. OAuth State Creation Fail-Closed
- If Redis fails to persist the generated OAuth state or verifier during `/api/v1/auth/github/login`, the handler **aborts immediately**:
  - No redirect to GitHub is issued.
  - No state cookie is placed in the browser.
  - Returns `HTTP 503 Service Unavailable`.

### 3. OAuth State Consumption Fail-Closed
- If Redis raises an error or times out during state consumption in `/api/v1/auth/github/callback`, the handler **aborts**:
  - Code exchange with GitHub is aborted.
  - State cookie is cleared from the browser.
  - Returns `HTTP 503 Service Unavailable`.

---

## 5. Cookie & CSRF Protection Policy

### Authentication Cookie Settings
- **Cookie Name**: `auth_token` (configurable via `AUTH_COOKIE_NAME`).
- **HTTP-Only**: `httponly=True` (JavaScript cannot inspect or exfiltrate the token).
- **Secure**: Controlled by `COOKIE_SECURE` (`True` in production, required by config validator).
- **SameSite**: Controlled by `COOKIE_SAMESITE` (`lax`, `strict`, or `none`).
- **Path**: Set to `/` for consistency across all platform routes.

### CSRF Protection for Cookie-Authenticated Mutations
State-changing HTTP requests (`POST`, `PUT`, `PATCH`, `DELETE`) authenticated via cookies require valid origin verification:
- Evaluates `Origin` header against `settings.cors_origins`.
- If `Origin` is missing (e.g. older browsers), falls back to extracting host from `Referer`.
- In `production` mode, requests lacking both `Origin` and `Referer` are rejected with `HTTP 403 Forbidden`.
- Safe HTTP methods (`GET`, `HEAD`, `OPTIONS`) and Bearer token requests (which cannot be forged via browser ambient credentials) are exempted.

### Open Redirect Prevention
OAuth callback redirect destinations are validated through `_resolve_trusted_frontend_url`:
- Only origins explicitly present in `settings.cors_origins` or matching `settings.frontend_url` are permitted.
- Relative paths (e.g. `/dashboard`) are normalized against `settings.frontend_url`.
- Arbitrary external targets (e.g. `https://evil.com`, `//evil.com`, `javascript:...`) are rejected and safely defaulted to `settings.frontend_url`.

---

## 6. Environment Variables

| Variable | Type | Default | Required in Production | Description |
|---|---|---|---|---|
| `JWT_SECRET` | `str` | — | **Yes** (>= 32 chars) | Symmetric HMAC secret for platform JWT signing |
| `JWT_ALGORITHM` | `str` | `"HS256"` | No | Algorithm for platform tokens (`HS256`, `HS384`, `HS512`) |
| `JWT_EXPIRE_MINUTES` | `int` | `15` | No (max 1440) | Platform access token lifespan |
| `JWT_ISSUER` | `str` | `"agent-platform"` | **Yes** (non-empty) | Platform token issuer claim (`iss`) |
| `JWT_AUDIENCE` | `str` | `"agent-platform-web"` | **Yes** (non-empty) | Platform token audience claim (`aud`) |
| `COOKIE_SECURE` | `bool` | `False` (`True` in prod) | **Yes** (must be `True`) | Enforce HTTPS-only cookie transmission |
| `COOKIE_SAMESITE` | `str` | `"lax"` | No | Cookie SameSite attribute (`lax`, `strict`, `none`) |
| `FRONTEND_URL` | `str` | `"http://localhost:5173"` | **Yes** (non-localhost) | Canonical frontend application origin |
| `CORS_ALLOWED_ORIGINS`| `str` | `"http://localhost:5173..."`| **Yes** (non-localhost) | Comma-separated list of trusted client origins |

---

## 7. Token Cutover & Session Invalidation Policy

Because platform JWT validation now strictly validates `iss`, `aud`, `token_type`, and `jti`:
- Tokens issued prior to Batch 1 hardening lack the `iss`, `aud`, or `token_type` claims.
- These legacy tokens are cleanly rejected upon decoding with `401 Unauthorized` (`ErrorCode.UNAUTHORIZED`, `"Invalid access token."`).
- Because access tokens are short-lived (default 15 minutes), clients will simply refresh their session by authenticating through GitHub OAuth.
- No insecure backward-compatibility bypass is permitted, guaranteeing zero acceptance of weakly structured tokens.

---

## 8. PKCE Support Decision & Verification Evidence

### Analysis & GitHub Specification Alignment
During pre-implementation review, GitHub's OAuth 2.0 documentation was audited regarding PKCE (RFC 7636) support:
- **Challenge Method:** GitHub supports `S256` for `code_challenge_method`. Plain text challenges are prohibited.
- **Grant Types:** Supported across standard authorization code grant flows for both OAuth Apps and GitHub Apps.
- **Client Confidentiality:** For confidential server-side clients, GitHub accepts `code_verifier` in conjunction with `client_secret` during `POST https://github.com/login/oauth/access_token`.
- **Implementation Decision:** PKCE S256 is implemented in full. The backend generates high-entropy `code_verifier` (64 bytes URL-safe base64), computes SHA-256 `code_challenge`, binds it to the Redis state entry, and forwards `code_verifier` in the token exchange.

---

## 9. Deployment & Operational Considerations

1. **Redis Engine Version & Cluster Compatibility**:
   - Native atomic `GETDEL` requires Redis 6.2+.
   - For environments running Redis <6.2 or managed proxies with restricted command sets, an atomic Lua fallback script is provided (`redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1])`).
   - If Redis connection drops or cluster failover occurs, all OAuth state operations and token revocation checks fail closed (`HTTP 503 Service Unavailable`).
2. **Rolling Deployments & Token Cutover**:
   - Access tokens have a default TTL of 15 minutes.
   - During rolling updates, old tokens without `iss`/`aud` will fail validation on updated nodes. Frontends automatically redirect unauthenticated users to `/login`.
   - To achieve seamless transitions, configure `FRONTEND_URL` and `CORS_ALLOWED_ORIGINS` across all environment deployments before rolling update.
3. **Cookie Security in Production**:
   - In production (`APP_ENV=production`), `COOKIE_SECURE=True` is strictly enforced by configuration validation.
   - Cookie deletions (`_clear_state_cookie` and `/logout`) emit matching `secure=True`, `httponly=True`, and `samesite` attributes, preventing RFC 6265bis cookie deletion drops in modern browsers.
