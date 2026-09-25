# GitHub App Setup Guide

This document covers how to register and configure the GitHub App used by the
AI-Powered Software Development Platform.  Follow these steps once — all team
members share the same App credentials via environment variables.

---

## 1. Register the GitHub App

1. Log in to GitHub as the **organization owner** (or your personal account for local dev).
2. Navigate to **Settings → Developer settings → GitHub Apps → New GitHub App**.
3. Fill in the form:

| Field | Value |
|-------|-------|
| **GitHub App name** | `AI Dev Platform (local)` *(use a unique suffix per environment)* |
| **Homepage URL** | `http://localhost:3000` |
| **Callback URL** | `http://localhost:3000/auth/github/callback` |
| **Webhook URL** | Use [ngrok](https://ngrok.com/) for local dev: `https://<your-ngrok-id>.ngrok.io/api/v1/webhooks/github` |
| **Webhook secret** | Generate with `openssl rand -hex 32` — save this value |

4. Under **Repository permissions**, grant:

| Permission | Level |
|------------|-------|
| Contents | Read |
| Metadata | Read (mandatory) |
| Pull requests | Write |

5. Under **Subscribe to events**, check: **Push**, **Pull request**, **Installation**.

6. Click **Create GitHub App**.

---

## 2. Generate and Store the Private Key

1. On the newly created App page, scroll to **Private keys**.
2. Click **Generate a private key** — a `.pem` file downloads automatically.
3. **Never commit this file.** Store it as an environment variable:

```bash
# On Linux/macOS — convert newlines to \n for .env storage
GITHUB_APP_PRIVATE_KEY=$(cat path/to/your-app.pem | awk '{printf "%s\\n", $0}')
```

4. Add to your `.env` file (see `.env.example` for the full list of keys).

---

## 3. Record Required Credentials

After creating the App, note the following values from the App settings page:

| Environment Variable | Where to find it |
|----------------------|-----------------|
| `GITHUB_APP_ID` | Shown at the top of the App page as "App ID" |
| `GITHUB_APP_PRIVATE_KEY` | The contents of the `.pem` file (newlines escaped as `\n`) |
| `GITHUB_CLIENT_ID` | Labeled "Client ID" on the App page |
| `GITHUB_CLIENT_SECRET` | Click "Generate a new client secret" |
| `GITHUB_WEBHOOK_SECRET` | The value you chose in Step 1 |

---

## 4. Environment Variables Reference

All values go into `.env` at the project root (copy from `.env.example`):

```dotenv
# GitHub App
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----
GITHUB_CLIENT_ID=Iv1.abcdef1234567890
GITHUB_CLIENT_SECRET=<secret>
GITHUB_WEBHOOK_SECRET=<random-hex>
```

> **Security rule:** `.env` is in `.gitignore`.  Never push real credentials.

---

## 5. Local Development with ngrok

GitHub webhooks require a publicly reachable URL.  For local dev:

```bash
# Install ngrok (https://ngrok.com/download) and authenticate
ngrok http 8000
```

Copy the `https://` forwarding URL and paste it as the **Webhook URL** in the
GitHub App settings.  Re-register whenever the ngrok session restarts (ngrok
Pro provides a stable domain).

---

## 6. Install the App on a Repository

1. Go to your GitHub App page → **Install App**.
2. Choose the account/organization and select the repositories to grant access.
3. After installation, GitHub redirects to
   `http://localhost:3000/auth/github/callback?installation_id=<id>&setup_action=install`.
4. The backend handler stores this `installation_id` in the `github_installations` table.

---

## 7. Verifying the Setup

Run the following to confirm the App JWT signs correctly:

```python
from app.core.config import get_settings
from app.integrations.github.token_manager import InstallationTokenManager

settings = get_settings()
mgr = InstallationTokenManager(redis=None, settings=settings)
jwt_token = mgr._build_app_jwt()
print("App JWT generated successfully:", jwt_token[:30], "...")
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `401 Unauthorized` on App API | Clock skew on your machine | Sync system clock |
| `PEM key read error` | Literal `\n` not converted to newlines | Use `replace("\\n", "\n")` |
| Webhook `400 Bad Request` | Wrong `GITHUB_WEBHOOK_SECRET` | Re-generate and update both GitHub and `.env` |
| Token not cached | Redis not running | `docker-compose up redis` |
