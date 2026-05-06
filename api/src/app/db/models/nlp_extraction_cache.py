from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class NlpExtractionCache(Base):
    __tablename__ = "nlp_extraction_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
