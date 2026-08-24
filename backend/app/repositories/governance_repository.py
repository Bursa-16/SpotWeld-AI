"""Persistence adapter for append-only governed audit events.

Transaction ownership always remains with the caller.  This repository adds
and flushes records so database failures are visible inside the owning
transaction, but it never commits or rolls back that transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.governance import GovernedAuditEvent


class GovernanceRepository:
    """Store and retrieve governed audit events using a caller-owned session."""

    def __init__(self, session: Session):
        self.session = session

    def add_event(self, event: GovernedAuditEvent) -> GovernedAuditEvent:
        """Add one event and flush it without taking transaction ownership."""
        self.session.add(event)
        self.session.flush()
        return event

    def get_by_event_id(self, event_id: str) -> GovernedAuditEvent | None:
        """Return the event with the stable external identity, if present."""
        return self.session.scalar(
            select(GovernedAuditEvent).where(
                GovernedAuditEvent.event_id == event_id
            )
        )
