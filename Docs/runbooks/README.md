# Platform Operations Runbooks

Operational procedures for the AI-Powered Software Development Platform:

1. **[Deploy Per Role](./deploy_per_role.md)**: Independent deployment of `api`, `sync_worker`, `webhook_worker`, `task_worker`, and `runner` services.
2. **[Secret Rotation](./rotate_secrets.md)**: Zero-downtime rotation procedures for JWT secrets, GitHub App keys, and webhook secrets.
3. **[Webhook Replay](./replay_webhooks.md)**: Investigating failed webhook deliveries and dead-letter queue replay.
4. **[Task Recovery](./recover_tasks.md)**: Stale task reconciliation, crash recovery, and workspace cleanup.
5. **[Backup & Disaster Recovery Drill](./backup_restore.md)**: Database dump, verification, and point-in-time restore drill procedure (T9.7).
