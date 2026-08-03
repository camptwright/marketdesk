from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_bearer_token
from src.data.db_client import get_db
from src.models.orm import Position

router = APIRouter(
    prefix="/positions", dependencies=[Depends(require_bearer_token)], tags=["positions"]
)


class PositionRow(BaseModel):
    id: uuid.UUID
    symbol: str
    shares: float
    cost_basis: float
    opened_at: datetime
    closed_at: datetime | None


class CreatePositionRequest(BaseModel):
    symbol: str
    shares: float
    cost_basis: float
    opened_at: datetime


class UpdatePositionRequest(BaseModel):
    """All fields optional - PATCH semantics. Setting `closed_at` is how a
    position is closed; it's never DELETEd (see Position's docstring)."""

    shares: float | None = None
    cost_basis: float | None = None
    closed_at: datetime | None = None


def _row(p: Position) -> PositionRow:
    return PositionRow(
        id=p.id,
        symbol=p.symbol,
        shares=float(p.shares),
        cost_basis=float(p.cost_basis),
        opened_at=p.opened_at,
        closed_at=p.closed_at,
    )


@router.get("")
async def list_positions(
    include_closed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[PositionRow]:
    stmt = select(Position).order_by(Position.opened_at.desc())
    if not include_closed:
        stmt = stmt.where(Position.closed_at.is_(None))
    result = await db.execute(stmt)
    return [_row(p) for p in result.scalars().all()]


@router.post("", status_code=201)
async def create_position(
    request: CreatePositionRequest, db: AsyncSession = Depends(get_db)
) -> PositionRow:
    if request.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be positive")
    position = Position(
        symbol=request.symbol.strip().upper(),
        shares=request.shares,
        cost_basis=request.cost_basis,
        opened_at=request.opened_at,
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)
    return _row(position)


@router.patch("/{position_id}")
async def update_position(
    position_id: uuid.UUID,
    request: UpdatePositionRequest,
    db: AsyncSession = Depends(get_db),
) -> PositionRow:
    position = await db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="position not found")

    if request.shares is not None:
        if request.shares <= 0:
            raise HTTPException(status_code=400, detail="shares must be positive")
        position.shares = request.shares
    if request.cost_basis is not None:
        position.cost_basis = request.cost_basis
    if request.closed_at is not None:
        position.closed_at = request.closed_at

    await db.commit()
    await db.refresh(position)
    return _row(position)


@router.delete("/{position_id}", status_code=204)
async def delete_position(position_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    position = await db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="position not found")
    await db.delete(position)
    await db.commit()
