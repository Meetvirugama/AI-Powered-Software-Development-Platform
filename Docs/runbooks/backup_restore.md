# Runbook — Database Backup and Disaster Recovery Drill (T9.7)

This runbook documents the disaster recovery and backup/restore procedure for the PostgreSQL 15 + `pgvector` database and Redis state.

---

## 1. Backup Architecture & Policies

- **Engine:** PostgreSQL 15+ with `pgvector` extension.
- **RPO (Recovery Point Objective):** ≤ 1 hour (daily automated full dumps + WAL archiving).
- **RTO (Recovery Time Objective):** ≤ 30 minutes.
- **Target Storage:** Encrypted blob storage (e.g. Azure Blob Storage / AWS S3) with immutable versioning.

---

## 2. Automated Backup Drill Procedure

### Step 2.1 — Dump Production Database

```bash
# Export compressed PostgreSQL custom format dump
pg_dump -Fc --no-acl --no-owner \
  --dbname="${DATABASE_URL}" \
  -f "backup_drill_$(date +%Y%m%d_%H%M%S).dump"
```

### Step 2.2 — Verify Dump Integrity

Verify that critical schema tables, indexes, and vector embeddings are captured in the dump TOC:

```bash
pg_restore -l "backup_drill_*.dump" | grep -E "(tasks|analysis_runs|code_chunks|code_symbols|users)"
```

### Step 2.3 — Test Restore to Staging / Drill Instance

```bash
# 1. Create a transient restore test database
createdb -h localhost -p 5432 -U postgres dr_verification_test

# 2. Ensure pgvector extension is pre-installed
psql -h localhost -p 5432 -U postgres -d dr_verification_test -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. Restore dump
pg_restore -h localhost -p 5432 -U postgres -d dr_verification_test \
  --clean --if-exists --exit-on-error "backup_drill_*.dump"

# 4. Verify table row counts and vector index sanity
psql -h localhost -p 5432 -U postgres -d dr_verification_test -c "
  SELECT table_name, (xpath('/row/cnt/text()', xml_count))[1]::text::int as row_count
  FROM (
    SELECT table_name, query_to_xml(format('select count(*) as cnt from %I', table_name), false, true, '') as xml_count
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
  ) t;
"

# 5. Clean up drill database
dropdb -h localhost -p 5432 -U postgres dr_verification_test
```

---

## 3. Disaster Recovery Drill Checklist

1. [x] Daily automated backup enabled on managed database instance.
2. [x] Point-In-Time-Recovery (PITR) configured with 7-day retention window.
3. [x] Pre-flight restore verification drill executed and validated.
4. [x] Connection strings updated via key vault without hardcoded secrets.
