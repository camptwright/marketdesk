"""SQLAlchemy ORM models.

Three tables, deliberately simple:
  * `watchlist` - symbols the user wants tracked but doesn't own.
  * `positions` - actual holdings, open (closed_at IS NULL) or closed.
  * `price_snapshots` - OHLCV history, the append-only source of truth for
    /history and for computing day-change without hitting a provider on
    every request.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Watchlist(Base):
    __tablename__ = "watchlist"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(String(1000))


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    shares: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    cost_basis: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL = still open. A position is never deleted on "close" (DELETE is
    # for mistakes; closing is a PATCH setting this) so realized history
    # survives - portfolio math and any future P/L reporting depend on it.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceSnapshot(Base):
    """Append-only. A (symbol, ts) pair is captured once; re-snapshotting
    the same bar is a no-op (ON CONFLICT DO NOTHING at the call site), not
    an update - the provider's own numbers for a closed bar don't change."""

    __tablename__ = "price_snapshots"

    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (PrimaryKeyConstraint("symbol", "ts"),)
