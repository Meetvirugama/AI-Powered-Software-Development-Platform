import hashlib
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Assuming FileInfo is imported from the scanner module
# from scanner.symbols import FileInfo

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Return the SHA-256 hash of file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def should_reindex(
    content: str,
    existing_hash: str | None,
) -> bool:
    """Return True when a file is new or its content has changed."""
    if existing_hash is None:
        return True

    return compute_content_hash(content) != existing_hash


class IncrementalIndexer:
    """
    Day 5 Task for Divu: Incremental Indexing
    """
    def __init__(self, db_session: AsyncSession, chunker: Any = None, queue: Any = None):
        self._db = db_session
        self.chunker = chunker
        self.queue = queue

    async def sync(self, repository_id: UUID, scanned_files: list[Any]) -> dict[str, int]:
        """
        1. Fetch existing (path, content_hash) pairs from repository_files
        2. Compare with newly scanned files
        3. Skip unchanged files (hash match)
        4. For changed/new files: delete old chunks, re-scan, re-chunk, re-embed
        """
        logger.info(f"Starting incremental sync for repo {repository_id} with {len(scanned_files)} files")
        
        # 1. Fetch existing hashes from DB
        query = text("SELECT path, content_hash, id FROM repository_files WHERE repository_id = :repo_id")
        result = await self._db.execute(query, {"repo_id": repository_id})
        
        # Create mapping of path -> (content_hash, file_id)
        existing_files = {row.path: {"hash": row.content_hash, "file_id": row.id} for row in result.fetchall()}
        
        indexed_count = 0
        skipped_count = 0
        
        for file_info in scanned_files:
            try:
                # Read actual file content
                with open(file_info.path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.error(f"Could not read {file_info.path}: {e}")
                continue
                
            new_hash = compute_content_hash(content)
            file_data = existing_files.get(file_info.path, {})
            old_hash = file_data.get("hash")
            file_id = file_data.get("file_id")
            
            # 2 & 3. Compare hashes -> Skip unchanged
            if old_hash == new_hash:
                skipped_count += 1
                continue
                
            # 4. Changed or new -> Delete old chunks, re-index
            logger.info(f"Re-indexing changed/new file: {file_info.path}")
            
            if file_id:
                # Delete old chunks for this file
                delete_query = text(
                    """
                    DELETE FROM code_chunks 
                    WHERE repository_id = :repo_id AND file_id = :file_id
                    """
                )
                await self._db.execute(delete_query, {"repo_id": repository_id, "file_id": file_id})
                
                # Update the hash in repository_files
                update_query = text(
                    """
                    UPDATE repository_files 
                    SET content_hash = :hash 
                    WHERE id = :file_id
                    """
                )
                await self._db.execute(update_query, {"hash": new_hash, "file_id": file_id})
            else:
                import uuid
                file_id = uuid.uuid4()
                insert_query = text(
                    """
                    INSERT INTO repository_files (id, repository_id, path, content_hash)
                    VALUES (:id, :repo_id, :path, :hash)
                    """
                )
                await self._db.execute(insert_query, {
                    "id": file_id,
                    "repo_id": repository_id,
                    "path": file_info.path,
                    "hash": new_hash
                })
            
            # Integration Fix (Day 7): The Background Redis Worker and Scanner were never 
            # fully finished or scheduled for Week 2. To prevent the entire application's 
            # Sync button from being permanently broken, we synchronously insert the file 
            # chunk directly into the database here.
            import uuid, json
            
            chunk_id = uuid.uuid4()
            token_count = len(content.split())
            chunk_hash = compute_content_hash(content)
            
            chunk_query = text(
                """
                INSERT INTO code_chunks 
                (id, repository_id, file_id, content, token_count, embedding, start_line, end_line, content_hash, metadata)
                VALUES (:id, :repo_id, :file_id, :content, :tokens, :embedding, :start, :end, :hash, :metadata)
                """
            )
            
            # Using a 1536-dimensional zero vector as a placeholder since Meet's LexicalRetriever 
            # uses FTS on the content and doesn't rely on the vector.
            zero_embedding = [0.0] * 1536
            metadata_json = json.dumps({"file_path": str(file_info.path)})
            
            await self._db.execute(chunk_query, {
                "id": chunk_id,
                "repo_id": repository_id,
                "file_id": file_id,
                "content": content,
                "tokens": token_count,
                "embedding": str(zero_embedding),
                "start": 1,
                "end": max(1, len(content.splitlines())),
                "hash": chunk_hash,
                "metadata": metadata_json
            })

            indexed_count += 1

        await self._db.commit()
        return {"indexed": indexed_count, "skipped": skipped_count}