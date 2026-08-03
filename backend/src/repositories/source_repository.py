"""
Source repository - handles all database operations for video sources.
"""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, Dict, Any  # Dict/Any kept for return type hints
import logging

logger = logging.getLogger(__name__)


class SourceRepository:
    """Repository for source-related database operations."""

    @staticmethod
    async def create_source(
        db: AsyncSession, source_type: str, title: str, url: Optional[str] = None
    ) -> str:
        """Create a new source record and return its ID."""
        source_id = str(uuid4())
        try:
            result = await db.execute(
                text(
                    """
                    INSERT INTO sources (id, type, title, url, created_at, updated_at)
                    VALUES (:source_id, :source_type, :title, :url, NOW(), NOW())
                    RETURNING id
                    """
                ),
                {
                    "source_id": source_id,
                    "source_type": source_type,
                    "title": title,
                    "url": url,
                },
            )
            source_id = result.scalar()
            await db.commit()
        except Exception:
            await db.rollback()
            result = await db.execute(
                text(
                    """
                    INSERT INTO sources (id, type, title, created_at, updated_at)
                    VALUES (:source_id, :source_type, :title, NOW(), NOW())
                    RETURNING id
                    """
                ),
                {
                    "source_id": source_id,
                    "source_type": source_type,
                    "title": title,
                },
            )
            source_id = result.scalar()
            await db.commit()

        logger.info(f"Created source {source_id}: {title} ({source_type})")
        return source_id

    @staticmethod
    async def get_source_by_id(
        db: AsyncSession, source_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get source by ID."""
        result = await db.execute(
            text("SELECT * FROM sources WHERE id = :source_id"),
            {"source_id": source_id},
        )
        row = result.fetchone()

        if not row:
            return None

        return {
            "id": row.id,
            "type": row.type,
            "title": row.title,
            "url": getattr(row, "url", None),
            "created_at": row.created_at,
        }

    @staticmethod
    async def update_source_title(db: AsyncSession, source_id: str, title: str) -> None:
        """Update the title of a source."""
        await db.execute(
            text("UPDATE sources SET title = :title WHERE id = :source_id"),
            {"title": title, "source_id": source_id},
        )
        await db.commit()
        logger.info(f"Updated source {source_id} title to: {title}")

    @staticmethod
    async def delete_source_if_unreferenced(
        db: AsyncSession, source_id: str
    ) -> Optional[Dict[str, Any]]:
        """Delete a source, but only while no task points at it.

        Returns the deleted row, or None when a task still references the
        source. The NOT EXISTS guard keeps the delete safe if two tasks ever
        share one source.
        """
        result = await db.execute(
            text(
                """
                DELETE FROM sources
                WHERE id = :source_id
                  AND NOT EXISTS (
                      SELECT 1 FROM tasks WHERE source_id = :source_id
                  )
                RETURNING id, url
                """
            ),
            {"source_id": source_id},
        )
        row = result.fetchone()
        await db.commit()

        if not row:
            return None

        logger.info(f"Deleted source {source_id}")
        return {"id": row.id, "url": getattr(row, "url", None)}

    @staticmethod
    async def is_source_url_in_use(db: AsyncSession, url: str) -> bool:
        """Report whether a source still points at this URL."""
        result = await db.execute(
            text("SELECT 1 FROM sources WHERE url = :url LIMIT 1"),
            {"url": url},
        )
        return result.fetchone() is not None
