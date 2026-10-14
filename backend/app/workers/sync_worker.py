"""
Worker entrypoint for background sync jobs.
Connects the Redis `sync_jobs` queue to the processor.
"""

from __future__ import annotations

from app.services.sync_worker import process_sync_job, sync_worker_loop

__all__ = ["process_sync_job", "sync_worker_loop"]
