# Runbook: Secret Rotation Procedure

## 1. Overview
This runbook documents zero-downtime rotation procedures for production credentials:
- JWT Signing Key (`JWT_SECRET`)
- GitHub App Private Key (`GITHUB_APP_PRIVATE_KEY`)
- GitHub Webhook Secret (`GITHUB_WEBHOOK_SECRET`)
- Internal Runner Shared Secret (`RUNNER_AUTH_SECRET`)

---

## 2. JWT Secret Rotation (`JWT_SECRET`)

### Requirements
- Minimum 32 characters in length.
- Minimum 12 distinct characters (entropy guard in `backend/app/core/config.py`).
- Not in the disallowed dummy list (`secret`, `changeme`, `placeholder`, etc.).

### Zero-Downtime Rotation Steps
1. **Generate New Secret**:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. **Update Environment in Cloud Key Vault** (Azure Key Vault / Doppler / AWS Secrets Manager).
3. **Deploy API Instances**: Existing sessions survive via refresh token exchange (`/api/v1/auth/refresh`), issuing new access tokens under the rotated secret.
4. **Purge Revocation Cache**:
   ```bash
   redis-cli -u $REDIS_URL DEL "auth:blocklist:*"
   ```

---

## 3. GitHub App Private Key Rotation

1. Go to GitHub Organization Settings -> GitHub Apps -> Edit App.
2. Under **Private keys**, click **Generate a private key**.
3. Download the new PEM key.
4. Update `GITHUB_APP_PRIVATE_KEY` in Azure App Service / production environment.
5. Restart the API instances.
6. Verify GitHub API calls succeed: `GET /api/v1/health/ready`.
7. Once verified, delete the old private key in GitHub App settings.

---

## 4. GitHub Webhook Secret Rotation

1. In GitHub App settings, set the new Webhook Secret under **General** -> **Webhook secret**.
2. Immediately update `GITHUB_WEBHOOK_SECRET` in the `api` and `webhook_worker` environment variables.
3. Deploy/reload API and Webhook Worker.
4. Trigger a test event or ping from GitHub App UI and verify `200 OK` in delivery logs.
