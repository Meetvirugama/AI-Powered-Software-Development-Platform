"""Automated regression test for Non-Functional Load & Soak Suite (TST-N1..N3)."""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.analysis_finding import AnalysisFinding
from app.services.analysis_run_history_service import AnalysisRunHistoryService
from app.services.sse_redis_streams import RedisStreamEventBroker


def test_tst_n2_sse_channel_dispatch_benchmark() -> None:
    broker = RedisStreamEventBroker()
    users = [f"user_{i}" for i in range(100)]
    latencies: list[float] = []

    for uid in users:
        t0 = time.perf_counter()
        stream_key = broker.build_stream_key(uid, "platform_events")
        dt_us = (time.perf_counter() - t0) * 1_000_000.0
        latencies.append(dt_us)
        assert uid in stream_key

    p95 = statistics.quantiles(latencies, n=20)[18]
    assert p95 < 500.0, f"Per-user stream key resolution p95 ({p95}µs) exceeded threshold"


def test_tst_n3_retention_purge_and_table_bounding() -> None:
    engine = create_engine("sqlite:///:memory:", echo=False)
    AnalysisRun.metadata.create_all(bind=engine, tables=[AnalysisRun.__table__, AnalysisFinding.__table__])
    LocalSession = sessionmaker(bind=engine)
    db = LocalSession()

    try:
        repo_id = uuid.uuid4()
        history_service = AnalysisRunHistoryService()

        for day in range(35):
            created = datetime.now(timezone.utc) - timedelta(days=day)
            history_service.save_run(
                {
                    "repository_id": repo_id,
                    "feature_type": AnalysisFeature.DETECT_BUGS.value,
                    "status": AnalysisRunStatus.COMPLETED.value,
                    "result_payload": {"test": True, "day": day},
                    "created_at": created,
                },
                db=db,
            )
        db.commit()

        initial_count = db.query(AnalysisRun).filter(AnalysisRun.repository_id == repo_id).count()
        assert initial_count == 35

        purged = history_service.purge_expired_runs(repository_id=repo_id, retention_days=14, db=db)
        db.commit()

        retained_count = db.query(AnalysisRun).filter(AnalysisRun.repository_id == repo_id).count()
        assert purged == 21
        assert retained_count == 14
    finally:
        db.close()
        engine.dispose()
