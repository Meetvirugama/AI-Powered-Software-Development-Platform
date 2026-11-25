# Azure manual actions

The repository identifies the API App Service as `ai-powered-dev-platform-api` and the sync worker as `ai-powered-dev-platform-worker`. The runner host, deployed settings and API resource group were unavailable for inspection. No Azure resources were modified. There is no new database migration for this change.

## Required when using the remote runner

The API edits a task checkout before asking the runner to test it. Both hosts must see the same checkout at the same absolute path.

1. In the API App Service, open **Settings → Configuration → Path mappings → New Azure Storage Mount**. Mount a private writable share as `/mounts/task-workspaces` or an approved equivalent. Mount the same share at the same path on the runner host. The runner resource name depends on your deployment. Validate filesystem permissions, Git locking and rename behavior on the share. [Microsoft Azure Storage mounts](https://learn.microsoft.com/en-us/azure/app-service/configure-connect-to-azure-storage)
2. Open **Settings → Environment variables → App settings** on `ai-powered-dev-platform-api`. Set `TASK_WORKSPACE_ROOT=/mounts/task-workspaces`, and set the same value for the runner process. Keep `SANDBOX_BACKEND=runner`, set `RUNNER_BASE_URL` to the actual private runner URL and keep matching `RUNNER_AUTH_SECRET` references on both services. A settings change restarts App Service. [Microsoft App Service settings](https://learn.microsoft.com/en-us/azure/app-service/configure-common?tabs=cli)
3. Redeploy the API and runner together in staging. Confirm the runner health endpoint reports a container backend. Approve a small task against a test repository, then compare the tested diff, verified commit and Draft PR head. Verify that the isolated test container cannot write Git metadata. Keep the real installation token and runner secret out of logs.
4. To roll back, redeploy the previous API and runner versions together and restore the prior settings. Retain the share until in-flight task data has been reconciled.

For the API setting, the equivalent Azure CLI command is:

```sh
az webapp config appsettings set \
  --resource-group "<API resource group>" \
  --name ai-powered-dev-platform-api \
  --settings TASK_WORKSPACE_ROOT=/mounts/task-workspaces \
  --output none
```

## Service checks

Use the staging deployment to confirm PostgreSQL and Redis connectivity, GitHub App contents and pull-request permissions, model availability, runner timeouts, and release migration configuration. The existing sync worker handles repository sync. It does not run native Task Planner jobs.

## Phase 1 performance rollout (manual Azure steps)

1. **Enable Always On** on both App Services so Azure never unloads idle containers:
   ```sh
   az webapp config set --name ai-powered-dev-platform-api --resource-group ai-platform-rg --always-on true --output none
   az webapp config set --name ai-powered-dev-platform-worker --resource-group ai-platform-rg --always-on true --output none
   ```
2. **Confirm the sync worker `SERVICE_ROLE`**: ensure `ai-powered-dev-platform-worker` uses `SERVICE_ROLE=sync_worker_web` and `WEBSITES_PORT=8000` (also enforced by `.github/workflows/azure-sync-worker.yml`) so Azure's HTTP `/health` probe succeeds and stops ~230s probe-induced restarts.
3. **Decouple Alembic migrations from API startup**:
   - Add the `PRODUCTION_DATABASE_URL` GitHub Actions repository secret (matching the production `DATABASE_URL` used by `ai-powered-dev-platform-api`) so the CI `migrate-database` job runs `bash startup.sh migrate` before deploy.
   - Once `PRODUCTION_DATABASE_URL` is configured, set `RUN_MIGRATIONS_ON_STARTUP=false` on `ai-powered-dev-platform-api`.
